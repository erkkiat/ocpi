import base64
from datetime import datetime

import pytz
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging
from typing import Optional, List

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_save, pre_delete, post_save
from django.dispatch import receiver
from django.http import HttpResponseRedirect

import util
from ocpi22 import choices
from ocpi22.choices import CONNECTION_STATUS_CHOICES, \
    ENDPOINT_ROLE_CHOICES, OcpiModuleEnum, EndpointRoleEnum, ROLE_CHOICES, IDENTIFIER_CHOICES, OcpiRolesEnum
from ocpi22.credentials.util import find_endpoints_by_roles
from ocpi22.models.business_details import BusinessDetails
from ocpi22.ocpi.util import OcpiModule, OCPIResponse
from ocpi22.util import ModelUtilMixin, build_absolute_uri
from ocpiconnector.exception_handler import view_exception_handler
from ocpiconnector.manager import PartnerManager

# Todo: A PUT will switch to the version that contains this credentials endpoint if it’s different from
#  the current version. The server must fetch the client’s endpoints again, even if the version has not changed.
from ocpiconnector.ocpi_identities import get_our_party, Party


class Credentials(models.Model, ModelUtilMixin, OcpiModule):
    # Todo: Push HubCLientInfo in OCPI 2.2 format
    """
    Example:

    PUT To URL: https://www.server.com/ocpi/cpo/2.0/clientinfo/NL/ALL
    {
      "country_code": "NL",
      "party_id": "ALL",
      "role": "CPO",
      "status": "PLANNED",
    }
    """

    ocpi_serializer_class = 'ocpi22.ocpi.serializers.CredentialsSerializer'
    ocpi_module_name = OcpiModuleEnum.CREDENTIALS
    ocpi_object_owner = None
    send_updates_to = ('EMSP', 'NAP', 'NSP', 'HUB', 'CPO', 'SCSP', 'OTHER')

    objects = PartnerManager()

    class Meta:
        verbose_name = _('roaming partner')
        verbose_name_plural = _('roaming partners')

    # The credentials token used only for the initial connection, and is communicated manually between parties
    token_a = models.CharField(max_length=64, blank=True, default='', verbose_name=_('Token A'))

    # Our credentials token used for the actual communication
    ours = models.CharField(max_length=64, blank=True, default='', verbose_name=_('Our token'))

    # The other party's credentials token used for the actual communication
    theirs = models.CharField(max_length=64, blank=True, default='', verbose_name=_('Their token'))

    # URL to the versions endpoint
    url = models.URLField(blank=True, default='', verbose_name=_('Versions endpoint URL'))

    # Status of the connection to the party.
    connection_status = models.CharField(max_length=9, choices=CONNECTION_STATUS_CHOICES, default='CONNECTED',
                                         verbose_name=_('Responding'))

    # The timestamp for the last message received or succesfully sent to the other party
    last_connection = models.DateTimeField(null=True, blank=True, verbose_name=_('Last connection'))

    version = models.CharField(max_length=3, choices=choices.VERSION_CHOICES, blank=True, null=True,
                               verbose_name=_('Version'))

    # Connections are only accepted for valid Credentials
    valid = models.BooleanField(default=True, verbose_name=_('Activated'))

    def soft_delete(self):
        self.valid = False
        self.save(update_fields=['valid'])

    def delete(self, using=None, keep_parents=False):
        self.soft_delete()

    def reset(self):
        self.theirs = None
        self.ours = None
        self.url = None
        self.save(update_fields=['ours', 'theirs', 'url'])

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True, verbose_name=_('Last updated'))

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        return super(self.__class__, self).save(*args, **kwargs)

    def atomic_post_save(self, *_args, **_kwargs) -> None:
        """This should trigger when Credentials is modified in Admin UI or pushed over HubClientInfo"""
        find_endpoints_by_roles.cache_clear()
        # from ocpi22.pull import schedule_full_update
        # schedule_full_update(self, countdown=1)
        # if ocpi_platform.is_hub:
        #     self.send_all_updates(ocpi_module_name=OcpiModuleEnum.HUBCLIENTINFO)

    def party(self) -> str:
        return ", ".join([
            f'{r.country_code}*{r.party_id} ({r.role})'
            for r in self.roles.all()
        ])

    party.short_description = _('Parties')  # For admin UI

    @staticmethod
    def base64(token: models.CharField):
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')

    def token_a_base64(self):
        return self.base64(self.token_a)

    def ours_base64(self):
        if not self.ours:
            return ''
        return self.base64(self.ours)

    def theirs_base64(self):
        return self.base64(self.theirs)

    @staticmethod
    def find(token: str, create=False):
        """
        Find a Credentials object by OCPI token
        @param token: token string raw, not base64
        @param create: should the Credentials be created if not found
        @return: Credentials object or None
        """
        credentials = Credentials.objects.filter(Q(token_a=token) | Q(ours=token) | Q(theirs=token))
        count = credentials.count()
        assert count <= 1, f"There are overlapping tokens in credentials {', '.join([str(a.pk) for a in credentials])}."
        if credentials.count() == 1:
            return credentials.first()
        return Credentials.objects.create(token_a=token) if create else None

    def is_complete(self) -> bool:
        return bool(self.ours and self.theirs and self.roles.count())

    def responding(self) -> bool:
        return bool(self.connection_status == choices.CONNECTED)

    # For admin so that there is a pretty boolean icon and sorting
    responding.boolean = True
    responding.admin_order_field = 'connection_status'

    def update_last_connection(self):
        self.last_connection = datetime.now(pytz.utc)
        self.connection_status = choices.CONNECTED
        self.save(update_fields=['last_connection', 'connection_status'])

    def get_party_for_role(self, role: OcpiRolesEnum) -> Optional[Party]:
        credentialsrole = self.roles.filter(role=role.value).first()
        if credentialsrole:
            return credentialsrole.party

    def get_role(self, party: Party):
        """
        Get the CredentialsRole for a party
        @param party: The party, usually from request headers
        @return: CredentialsRole or None
        """
        roles = self.roles.filter(country_code__iexact=party.country_code, party_id__iexact=party.party_id)
        if roles.count() == 1:
            return roles.first()
        return None

    def get_parties(self) -> List[Party]:
        return [r.party for r in self.roles.all()]

    @property
    def is_hub(self) -> bool:
        return bool(self.get_party_for_role(OcpiRolesEnum.HUB))

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
                **data, defaults=dict(country_code=data.get('country_code', ''),
                                      party_id=data.get('party_id', ''),
                                      business_details=business_details)
            )
            self.roles.add(role)
            return role
        else:
            raise ValidationError(serializer.errors)

    def get_admin_url(self):
        from util import reverse
        return build_absolute_uri(reverse('admin:ocpi22_credentials_change', args=[self.pk]))

    @property
    def name(self):
        return " / ".join([role.business_details.name for role in self.roles.all()]) or 'N/A'

    @property
    def status_display(self):
        if not self.valid or self.connection_status in {choices.PLANNED, choices.SUSPENDED}:
            return 'muted'
        return 'ok' if bool(self.responding()) else 'error'

    def __hash__(self):
        return util.member_hash(self)


class CredentialsRole(models.Model, ModelUtilMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['country_code', 'party_id', 'role'], name='unique_credentialsroles'),
            # Todo: Should we really allow multiple roles for a single country_code+party_id?
        ]
        verbose_name = _('party')
        verbose_name_plural = _('parties')

    objects = PartnerManager()

    role = models.CharField(max_length=5, choices=ROLE_CHOICES, verbose_name=_('Role'))

    business_details = models.ForeignKey(BusinessDetails, on_delete=models.PROTECT, related_name='credentialsroles',
                                         verbose_name=_('Business details'))

    # ISO-3166 alpha-2 country code
    country_code = models.CharField(max_length=2, choices=choices.COUNTRY_CHOICES, verbose_name=_('Country code'))

    # ID of the party
    party_id = models.CharField(max_length=3, verbose_name=_('Party ID'))

    credentials = models.ForeignKey(Credentials, related_name='roles', on_delete=models.CASCADE, null=True,
                                    verbose_name=_('Credentials'))

    agreed_parties = models.ManyToManyField('ocpi22.CredentialsRole', blank=True, related_name='agreed_parties_backwards',
                                            verbose_name=_('Parties with agreements'))
    # Todo: Agreed parties should show on both sides, if CPO has an agreement with MSP, then MSP should also see it (in admin)

    class ocpi_master:
        @property
        def country_code(self):
            return self.country_code

        @property
        def party_id(self):
            return self.party_id

    def __str__(self):
        if self.role:
            return f'{self.country_code}*{self.party_id} ({self.role})'
        return f'{self.country_code}*{self.party_id}'

    @property
    def party(self) -> Party:
        return Party(str(self.country_code), str(self.party_id))

    def party_str(self) -> str:
        return f'{self.country_code}*{self.party_id}'
    party_str.short_description = _('Party')  # For admin UI

    def __hash__(self):
        return hash(f'{self.country_code}{self.party_id}{self.role}')

    @classmethod
    def find_by_party(cls, party: Party) -> Optional['CredentialsRole']:
        return cls.objects.filter(country_code__iexact=party.country_code,
                                  party_id__iexact=party.party_id).first()


class Endpoint(models.Model, ModelUtilMixin):
    identifier = models.CharField(max_length=13, choices=IDENTIFIER_CHOICES, verbose_name=_('Identifier'))

    url = models.URLField(verbose_name=_('URL'))

    role = models.CharField(max_length=8, choices=ENDPOINT_ROLE_CHOICES, verbose_name=_('Role'))

    credentials = models.ForeignKey(Credentials, on_delete=models.CASCADE, related_name='endpoints',
                                    verbose_name=_('Credentials'))

    def __str__(self):
        return f'{self.get_identifier_display()} {self.get_role_display()} at {self.url}'

    def get_token_base64(self):
        token = self.credentials.theirs
        return base64.b64encode(str(token).encode('ascii')).decode('ascii')

    def __hash__(self):
        return util.member_hash(self)


class NewConnection(forms.Form):
    versions_url = forms.URLField()
    token_a = forms.CharField(max_length=64)


@view_exception_handler(redirect_url_name='admin:ocpi22_credentials_changelist',
                        view_name='the Credentials registration')
def new_connection(request):
    if not settings.PREMIUM:
        import premium
        premium.premium_message(request)
    else:
        if request.method == 'POST':
            form = NewConnection(request.POST)
            if form.is_valid():
                from ocpiconnector.management.commands import exchange_credentials
                command = exchange_credentials.Command()
                result = command.handle(token_a=form.cleaned_data.get('token_a'),
                                        versions_endpoint_url=form.cleaned_data.get('versions_url'))
                if isinstance(result, OCPIResponse):
                    result = result.data.get('status_message')
                messages.success(request,
                                 result if isinstance(result, str) else _('A new connection has been established'))
            else:
                messages.error(request, form.errors)

    from util import reverse
    return HttpResponseRedirect(reverse('admin:ocpi22_credentials_changelist'))


@receiver(pre_save, sender=Credentials)
def credentials_pre_save(sender, instance, *_args, raw=False, **_kwargs):
    if raw:  # Skip this if installing fixtures
        return
    credentials: Credentials = instance
    if not credentials.valid:
        credentials.connection_status = choices.SUSPENDED
        credentials.last_connection = datetime.now(pytz.utc)
    if credentials.ours and credentials.theirs and credentials.token_a:
        credentials.token_a = ''


@receiver(post_save, sender=Credentials)
def credentials_post_save(sender, instance, *_args, raw, **_kwargs):
    if raw:
        return
    credentials: Credentials = instance
    if credentials.is_complete():
        credentials.atomic_post_save()


@receiver(pre_delete, sender=Credentials)
def credentials_delete(sender, instance, *_args, **_kwargs):
    # Send a DELETE to the other party, no reason to keep an expired Credentials
    credentials: Credentials = instance
    our_party: Party = get_our_party()
    if our_party:
        from ocpi22.tasks import send_ocpi_request
        data = dict()
        e = credentials.endpoints.filter(
            identifier=OcpiModuleEnum.CREDENTIALS.value,
            role=EndpointRoleEnum.RECEIVER.value
        ).first()
        if e:
            logging.info(f'Send delete to Credentials module at {e.url}')
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


def store_endpoints_for_party(credentials, endpoints):
    credentials.version = endpoints['version'].replace('.', '')  # "2.2" => "22"
    credentials.last_connection = datetime.now(pytz.utc)
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
