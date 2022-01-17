import base64
import secrets

from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_save
from django.dispatch import receiver

from ocpi22.models.models import BusinessDetails
from ocpi22.util import ModelUtilMixin, generate_random_token
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID


class Credentials(models.Model, ModelUtilMixin):
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

    VERSION_CHOICES = (
        ('22', '2.2'),
        ('211', '2.1.1')
    )
    version = models.CharField(max_length=10, choices=VERSION_CHOICES, blank=True, null=True)

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'Credentials for {" / ".join([str(s) for s in self.roles.all()])}'

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        return super(self.__class__, self).save(*args, **kwargs)

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


class CredentialsRole(models.Model, ModelUtilMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['country_code', 'party_id', 'role'], name='unique_credentialsroles'),
        ]

    ROLE_CHOICES = (
        ('CPO', 'Charge Point operator'),
        ('EMSP', 'Emobility Service Provider'),
        ('HUB', 'Hub'),
        ('NAP', 'National Access Point'),
        ('NSP', 'Navigation Service Provider'),
        ('OTHER', 'Other'),
        ('SCSP', 'Smart Charging Service Provider'),
    )

    role = models.CharField(max_length=5, choices=ROLE_CHOICES)

    business_details = models.ForeignKey(BusinessDetails, on_delete=models.PROTECT, related_name='credentialsroles')

    # ISO-3166 alpha-2 country code
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # ID of the party
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    credentials = models.ManyToManyField(Credentials, related_name='roles')

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

    IDENTIFIER_CHOICES = (
        (CREDENTIALS, 'Credentials'),
        (LOCATIONS, 'Locations'),
        (TOKENS, 'Tokens'),
        (COMMANDS, 'Commands'),
        (TARIFFS, 'Tariffs'),
        (CDRS, 'Charge Detail Records'),
        (SESSIONS, 'Sessions'),
    )
    identifier = models.CharField(max_length=12, choices=IDENTIFIER_CHOICES)

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


@receiver(pre_save, sender=Credentials)
def credentials_pre_save(sender, instance, *_args, **_kwargs):
    credentials: Credentials = instance
    if not credentials.token_a:
        credentials.token_a = generate_random_token()
    # if not credentials.ours:
    #     credentials.ours = generate_random_token()