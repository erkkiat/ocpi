import base64
import logging
import secrets
from functools import lru_cache
from typing import Optional

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_save, pre_delete
from django.dispatch import receiver
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from icecream import ic

from ocpi22.choices import ROLE_CHOICES, CONNECTION_STATUS_CHOICES
from ocpi22.models.business_details import BusinessDetails
from ocpi22.ocpi_util import OcpiModule
from ocpi22.util import ModelUtilMixin, generate_random_token, PREMIUM_MESSAGE

# Todo: A PUT will switch to the version that contains this credentials endpoint if it’s different from
#  the current version. The server must fetch the client’s endpoints again, even if the version has not changed.
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


class Credentials(models.Model, ModelUtilMixin, OcpiModule):
    ocpi_serializer_class = 'ocpi22.api.CredentialsSerializer'
    ocpi_module_name = 'credentials'
    ocpi_object_owner = None
    send_updates_to = None

    class Meta:
        verbose_name_plural = 'credentials'

    upper_case_fields = ('token_a', 'ours', 'theirs')

    # The credentials token used only for the initial connection, and is communicated manually between parties
    token_a = models.CharField(max_length=64, default=secrets.token_hex(32))

    # Our credentials token used for the actual communication
    ours = models.CharField(max_length=64, blank=True, default='')

    # The other party's credentials token used for the actual communication
    theirs = models.CharField(max_length=64, blank=True, default='')

    # URL to the other party's versions endpoint
    url = models.URLField(blank=True, default='')

    # Status of the connection to the party.
    connection_status = models.CharField(max_length=9, choices=CONNECTION_STATUS_CHOICES, default='CONNECTED')

    # The timestamp for the last message received or succesfully sent to the other party
    last_connection = models.DateTimeField(null=True, blank=True)

    VERSION_CHOICES = (
        ('22', '2.2'),
        ('211', '2.1.1')
    )
    version = models.CharField(max_length=10, choices=VERSION_CHOICES, blank=True, null=True)

    # Connections are only accepted for valid Credentials
    valid = models.BooleanField(default=True)

    def soft_delete(self):
        self.valid = False
        self.save(update_fields=['valid'])

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return " / ".join([str(s) for s in self.roles.all()])

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        return super(self.__class__, self).save(*args, **kwargs)

    def atomic_post_save(self, *_args, **_kwargs) -> None:
        # This should trigger when Credentials is modified in Admin UI
        find_endpoints_by_roles.cache_clear()
        from ocpi22.pull import schedule_full_update
        schedule_full_update(self, countdown=10)

    def party(self):
        # noinspection PyUnresolvedReferences
        return ", ".join([
            f'{r.country_code}*{r.party_id} ({r.role})'
            for r in self.roles.all()
        ])

    @staticmethod
    def base64(token: models.CharField):
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')

    def token_a_base64(self):
        # noinspection PyUnresolvedReferences
        return self.base64(self.token_a)

    def ours_base64(self):
        # noinspection PyUnresolvedReferences
        return self.base64(self.ours)

    def theirs_base64(self):
        # noinspection PyUnresolvedReferences
        return self.base64(self.theirs)

    @staticmethod
    def find(token, create=False):
        # noinspection PyUnresolvedReferences
        credentials = Credentials.objects.filter(Q(token_a=token) | Q(ours=token) | Q(theirs=token))
        count = credentials.count()
        assert count <= 1, f"There are overlapping tokens in credentials {', '.join([str(a.pk) for a in credentials])}."
        if credentials.count() == 1:
            return credentials[0]
        # noinspection PyUnresolvedReferences
        return Credentials.objects.create(token_a=token) if create else None

    def is_complete(self) -> bool:
        return bool(self.ours and self.theirs and self.roles.count())

    def connection_state(self) -> bool:
        return self.valid and self.connection_status == 'CONNECTED'

    # For admin so that there is a pretty boolean icon
    connection_state.boolean = True
    connection_state.admin_order_field = 'connection_status'

    def update_last_connection(self):
        self.last_connection = timezone.now()
        self.save(update_fields=['last_connection'])


class CredentialsRole(models.Model, ModelUtilMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['country_code', 'party_id', 'role'], name='unique_credentialsroles'),
        ]

    role = models.CharField(max_length=5, choices=ROLE_CHOICES)

    business_details = models.ForeignKey(BusinessDetails, on_delete=models.PROTECT, related_name='credentialsroles')

    # ISO-3166 alpha-2 country code
    country_code = models.CharField(max_length=2)

    # ID of the party
    party_id = models.CharField(max_length=3)

    credentials = models.ForeignKey(Credentials, related_name='roles', on_delete=models.CASCADE, null=True)

    def __str__(self):
        return f'{self.country_code}*{self.party_id} ({self.role})'

    def references(self):
        return self.credentials.all().count()


class Endpoint(models.Model, ModelUtilMixin):
    CREDENTIALS = 'credentials'
    LOCATIONS = 'locations'
    TOKENS = 'tokens'
    COMMANDS = 'commands'
    TARIFFS = 'tariffs'
    CDRS = 'cdrs'
    SESSIONS = 'sessions'
    HUBCLIENTINFO = 'hubclientinfo'

    IDENTIFIER_CHOICES = (
        (CREDENTIALS, 'Credentials'),
        (LOCATIONS, 'Locations'),
        (TOKENS, 'Tokens'),
        (COMMANDS, 'Commands'),
        (TARIFFS, 'Tariffs'),
        (CDRS, 'Charge Detail Records'),
        (SESSIONS, 'Sessions'),
        (HUBCLIENTINFO, 'Hubclientinfo'),
    )
    identifier = models.CharField(max_length=13, choices=IDENTIFIER_CHOICES)

    url = models.URLField()

    # Todo: Everything should be case-insensitive
    SENDER = 'SENDER'
    RECEIVER = 'RECEIVER'

    ROLE_CHOICES = (
        (SENDER, 'Sender'),
        (RECEIVER, 'Receiver')
    )
    role = models.CharField(max_length=8, choices=ROLE_CHOICES)

    credentials = models.ForeignKey(Credentials, on_delete=models.CASCADE, related_name='endpoints')

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.get_identifier_display()} {self.get_role_display()} at {self.url}'

    def get_token_base64(self):
        token = self.credentials.theirs
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')


class NewConnection(forms.Form):
    versions_url = forms.URLField()
    token_a = forms.CharField(max_length=64)


def new_connection(request):
    if not settings.PREMIUM:
        messages.warning(request, PREMIUM_MESSAGE)
    else:
        try:
            if request.method == 'POST':
                form = NewConnection(request.POST)
                # ic(request.POST, form.fields)
                if form.is_valid():
                    from ocpiconnector.management.commands import exchange_credentials
                    command = exchange_credentials.Command()
                    result = command.handle(token_a=form.cleaned_data.get('token_a'),
                                            versions_endpoint_url=form.cleaned_data.get('versions_url'))
                    messages.success(request,
                                     result if isinstance(result, str) else 'A new connection has been established')
                else:
                    messages.error(request, form.errors)
        except SyntaxError as e:
            msg = str(e)
            if e.errno == 403:
                msg = 'The token is not accepted by the other party (HTTP 403)'
            messages.error(request, msg)

    return HttpResponseRedirect(reverse('admin:ocpi22_credentials_changelist'))


@receiver(pre_save, sender=Credentials)
def credentials_pre_save(sender, instance, *_args, **_kwargs):
    credentials: Credentials = instance
    if not credentials.token_a:
        credentials.token_a = generate_random_token()


@receiver(pre_delete, sender=Credentials)
def credentials_delete(sender, instance, *_args, **_kwargs):
    # Send a DELETE to the other party, no reason to keep an expired Credentials
    credentials: Credentials = instance
    our_country_code = get_our_country_code()
    our_party_id = get_our_party_id()
    if our_country_code and our_party_id:
        from ocpi22.tasks import send_ocpi_request
        data = dict()
        # noinspection PyUnresolvedReferences
        e = credentials.endpoints.filter(identifier=Endpoint.CREDENTIALS, role=Endpoint.RECEIVER).first()
        if e:
            logging.info(f'Send delete to Credentials module at {e.url}')
            role: CredentialsRole = credentials.roles.first()
            if not role:
                logging.error(f'Cannot find a Credentials endpoint for {credentials} to send a DELETE')
                return
            args = data, e.url, e.get_token_base64(), role.country_code, role.party_id, \
                   our_country_code, our_party_id, 'delete'
            retry_policy = dict(max_retries=5, interval_start=5)
            if settings.BACKGROUND_SEND in (True, 1, 'True', 'true'):
                send_ocpi_request.apply_async(args, retry=True, retry_policy=retry_policy)
            else:
                send_ocpi_request(*args)
            return
    logging.error(f'Cannot find our party ID to send a Credentials DELETE for {credentials}')


@lru_cache(maxsize=None)
def find_endpoints_by_roles(roles: Optional[tuple], ocpi_module_name: str) -> list:
    logging.info(f'Reading module {ocpi_module_name} endpoints for {roles} from database.')
    result = []
    role: CredentialsRole
    for role in CredentialsRole.objects.filter(role__in=roles). \
            select_related('credentials'):
        credentials = role.credentials
        country_code = role.country_code
        party_id = role.party_id
        # noinspection PyUnresolvedReferences
        result += [
            (endpoint.url, credentials.theirs_base64(), country_code, party_id)
            for endpoint in Endpoint.objects.filter(
                identifier=ocpi_module_name,
                role=Endpoint.RECEIVER,
                credentials=credentials,
            )
        ]
    return result
