import base64

from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging
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
from util import reverse
from django.utils import timezone

from ocpi22 import choices
from ocpi22.choices import CONNECTION_STATUS_CHOICES, \
    ENDPOINT_ROLE_CHOICES, OcpiModuleEnum, EndpointRoleEnum, ROLE_CHOICES, IDENTIFIER_CHOICES, OcpiRolesEnum
from ocpi22.models.business_details import BusinessDetails
from ocpi22.ocpi.util import OcpiModule, OCPIProtocolError
from ocpi22.util import ModelUtilMixin, generate_random_token, build_absolute_uri

# Todo: A PUT will switch to the version that contains this credentials endpoint if it’s different from
#  the current version. The server must fetch the client’s endpoints again, even if the version has not changed.
from ocpiconnector.ocpi_identities import get_our_party, Party


class Credentials(models.Model, ModelUtilMixin, OcpiModule):
    ocpi_serializer_class = 'ocpi22.ocpi.serializers.CredentialsSerializer'
    ocpi_module_name = OcpiModuleEnum.CREDENTIALS
    ocpi_object_owner = None
    send_updates_to = None

    class Meta:
        verbose_name_plural = 'credentials'

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
        ('221', '2.2.1')
    )
    version = models.CharField(max_length=3, choices=VERSION_CHOICES, blank=True, null=True)

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
        return " / ".join([str(s) for s in self.roles.all()])

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        return super(self.__class__, self).save(*args, **kwargs)

    def atomic_post_save(self, *_args, **_kwargs) -> None:
        # This should trigger when Credentials is modified in Admin UI
        find_endpoints_by_roles.cache_clear()
        from ocpi22.pull import schedule_full_update
        schedule_full_update(self, countdown=10)

    def party(self) -> str:
        return ", ".join([
            f'{r.country_code}*{r.party_id} ({r.role})'
            for r in self.roles.all()
        ])

    @staticmethod
    def base64(token: models.CharField):
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')

    def token_a_base64(self):
        return self.base64(self.token_a)

    def ours_base64(self):
        if not self.ours:
            self.ours = generate_random_token()
            self.save(update_fields=['ours'])
        return self.base64(self.ours)

    def theirs_base64(self):
        return self.base64(self.theirs)

    @staticmethod
    def find(token, create=False):
        credentials = Credentials.objects.filter(Q(token_a=token) | Q(ours=token) | Q(theirs=token))
        count = credentials.count()
        assert count <= 1, f"There are overlapping tokens in credentials {', '.join([str(a.pk) for a in credentials])}."
        if credentials.count() == 1:
            return credentials[0]
        return Credentials.objects.create(token_a=token) if create else None

    def is_complete(self) -> bool:
        return bool(self.ours and self.theirs and self.roles.count())

    def connection_state(self) -> bool:
        result = bool(self.valid and self.connection_status == choices.CONNECTED)
        if not result:
            logging.error(f'Connecting to party {self.party()} may not be possible: '
                          f'(Credentials {"valid" if self.valid else "NOT VALID"}, server {self.connection_status}')
        return result

    # For admin so that there is a pretty boolean icon
    connection_state.boolean = True
    connection_state.admin_order_field = 'connection_status'

    def update_last_connection(self):
        self.last_connection = timezone.now()
        self.save(update_fields=['last_connection'])

    def get_party_for_role(self, role: OcpiRolesEnum) -> Optional[Party]:
        credentialsrole = self.roles.filter(role=role).first()
        if credentialsrole:
            return credentialsrole.party

    def add_role(self, role: dict) -> "CredentialsRole":
        assert isinstance(role, dict), f'Role should be a dict, not "{role}"'
        from ocpi22.ocpi.serializers import RolesSerializer
        serializer = RolesSerializer(data=role)
        if serializer.is_valid():
            data = serializer.data
            bd = data.pop('business_details')
            business_details, _businessdetails_created = BusinessDetails.objects.get_or_create(
                name=bd.get('name'), website=bd.get('website', ''), defaults=dict(logo=bd.get('logo', ''))
            )

            role, _role_created = CredentialsRole.objects.get_or_create(
                **data, defaults=dict(business_details=business_details)
            )
            self.roles.add(role)
            return role
        else:
            raise ValidationError(serializer.errors)

    def get_admin_url(self):
        return build_absolute_uri(reverse('admin:ocpi22_credentials_change', args=[self.pk]))


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

    @property
    def party(self):
        return Party(self.country_code, self.party_id)


class Endpoint(models.Model, ModelUtilMixin):
    identifier = models.CharField(max_length=13, choices=IDENTIFIER_CHOICES)

    url = models.URLField()

    role = models.CharField(max_length=8, choices=ENDPOINT_ROLE_CHOICES)

    credentials = models.ForeignKey(Credentials, on_delete=models.CASCADE, related_name='endpoints')

    def __str__(self):
        return f'{self.get_identifier_display()} {self.get_role_display()} at {self.url}'

    def get_token_base64(self):
        token = self.credentials.theirs
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')


class NewConnection(forms.Form):
    versions_url = forms.URLField()
    token_a = forms.CharField(max_length=64)


def new_connection(request):
    if not settings.PREMIUM:
        import premium
        premium.premium_message(request)
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
        except (SyntaxError, OCPIProtocolError, ValueError, KeyError, ImproperlyConfigured) as e:
            msg = str(e)
            logging.error(msg, request)
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
    our_party: Party = get_our_party()
    if our_party:
        from ocpi22.tasks import send_ocpi_request
        data = dict()
        # noinspection PyUnresolvedReferences
        e = credentials.endpoints.filter(
            identifier=OcpiModuleEnum.CREDENTIALS.value,
            role=EndpointRoleEnum.RECEIVER.value
        ).first()
        if e:
            logging.info(f'Send delete to Credentials module at {e.url}')
            # noinspection PyUnresolvedReferences
            role: CredentialsRole = credentials.roles.first()
            if not role:
                logging.error(
                    f'{settings.HOSTNAME}: Cannot find a Credentials endpoint for {credentials} to send a DELETE')
                return
            args = data, e.url, e.get_token_base64(), role.country_code, role.party_id, \
                   our_party.country_code, our_party.party_id, 'delete'
            retry_policy = dict(max_retries=5, interval_start=5)
            if settings.BACKGROUND_SEND:
                send_ocpi_request.apply_async(args, retry=True, retry_policy=retry_policy)
            else:
                send_ocpi_request(*args)
            return
    logging.error(f'{settings.HOSTNAME}: Cannot find our party ID to send a Credentials DELETE for {credentials}')


@lru_cache(maxsize=None)
def find_endpoints_by_roles(roles: Optional[tuple], ocpi_module: OcpiModuleEnum) -> list:
    logging.info(f'Reading module {ocpi_module.value} endpoints for {roles} from database.')
    result = []
    role: CredentialsRole
    for role in CredentialsRole.objects.filter(role__in=roles). \
            select_related('credentials'):
        credentials = role.credentials
        country_code = role.country_code
        party_id = role.party_id
        result += [
            (endpoint.url, credentials.theirs_base64(), country_code, party_id, credentials)
            for endpoint in Endpoint.objects.filter(
                identifier=ocpi_module.value.capitalize(),
                role=EndpointRoleEnum.RECEIVER.value,
                credentials=credentials,
            ) if credentials.valid
        ]
    return result


def store_endpoints_for_party(credentials, endpoints):
    credentials.version = endpoints['version'].replace('.', '')  # "2.2" => "22"
    credentials.last_connection = timezone.now()
    credentials.save()

    # Replace any existing endpoints for this specific party
    credentials.endpoints.all().delete()

    for ep in endpoints['endpoints']:
        endpoint = Endpoint(**ep)
        endpoint.credentials = credentials
        endpoint.save()


def store_tokens_for_party(our_token, their_token, token_a, version) -> Credentials:
    credentials: Credentials = Credentials.find(token_a, create=True)
    assert their_token != credentials.token_a
    assert our_token != credentials.token_a
    if our_token:
        credentials.ours = our_token
    if token_a:
        credentials.token_a = token_a
    if their_token:
        credentials.theirs = their_token
    credentials.version = version.replace('.', '')
    credentials.save()
    return credentials
