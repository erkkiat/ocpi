import base64
import secrets
import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.html import format_html
from icecream import ic
from rest_framework.reverse import reverse

from ocpi22.util import hours_minutes, generate_random_token, check_ownership, Ocpi, OcpiModule
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID


class ModelUtilMixin:
    @classmethod
    def get_if_exists(cls, *args, **kwargs):
        # noinspection PyUnresolvedReferences
        objects = cls.objects.filter(*args, **kwargs)
        if objects.count():
            return objects[0]
        return None

    def party(self):
        if hasattr(self, 'location'):
            return f'{self.location.country_code}*{self.location.party_id}'
        if hasattr(self, 'country_code') and hasattr(self, 'party_id'):
            return f'{self.country_code}*{self.party_id}'
        return ''

    # noinspection PyUnresolvedReferences
    def is_ours(self) -> bool:
        # Returns true if we hold the master data for this object
        if hasattr(self, 'country_code') and self.country_code != settings.COUNTRY_CODE:
            return False
        if hasattr(self, 'party_id') and self.party_id != settings.PARTY_ID:
            return False
        return True

    def is_owner(self, request):
        if not hasattr(self, 'country_code') or not hasattr(self, 'party_id'):
            return False
        return check_ownership(request, self.country_code, self.party_id)


class BusinessDetails(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'business details'
        constraints = [
            models.UniqueConstraint(fields=['name', 'website'], name='businessdetails_name_website'),
        ]

    name = models.CharField(max_length=100)
    website = models.URLField(blank=True, default='')
    logo = models.URLField(blank=True, default='')

    def __str__(self):
        return self.name

    def referenced_locations(self):
        # noinspection PyUnresolvedReferences
        return self.owner_locations.all().count() + \
               self.operator_locations.all().count() + \
               self.owner_locations.all().count()

    def referenced_credentials(self):
        # noinspection PyUnresolvedReferences
        return self.credentialsroles.all().count()


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

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'Credentials for {" / ".join([str(s) for s in self.roles.all()])}'

    def save(self, *args, **kwargs):
        if hasattr(self, 'upper_case_fields'):
            for field in self.upper_case_fields:
                f = self.__getattribute__(field)
                if f:
                    upper_value = f.upper()
                    self.__setattr__(field, upper_value)
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


class Token(models.Model, ModelUtilMixin, OcpiModule):
    """
    A Token structure with data owned by the eMSP
    """

    ocpi_serializer_class = 'ocpi22.api.TokenSerializer'
    ocpi_module_name = Ocpi.Modules.TOKENS

    SENDER = None

    ALLOWED = 'ALLOWED'
    BLOCKED = 'BLOCKED'
    EXPIRED = 'EXPIRED'
    NO_CREDIT = 'NO_CREDIT'
    NOT_ALLOWED = 'NOT_ALLOWED'

    upper_case_fields = ('country_code', 'party_id', 'uid', 'contract_id', 'language')

    # ISO-3166 alpha-2 country code of the MSP that 'owns' this Token
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the MSP that 'owns' this Token (following the ISO-15118)
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Unique ID by which this Token can be identified.
    # This is the field used by CPO system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a APP_USER or AD_HOC_USER Token, it will be a uniquely, by the eMSP, generated ID.
    # This field is named uid instead of id to prevent confusion with: contract_id.
    uid = models.CharField(max_length=36, unique=True)

    AD_HOC_USER = 'AD_HOC_USER'
    APP_USER = 'APP_USER'
    OTHER = 'OTHER'
    RFID = 'RFID'

    TYPE_CHOICES = (
        ('AD_HOC_USER', 'Ad hoc'),
        ('APP_USER', 'App'),
        ('OTHER', 'Other'),
        ('RFID', 'RFID'),
    )
    type = models.CharField(max_length=11, choices=TYPE_CHOICES)

    # Uniquely identifies the EV Driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from
    # "eMI3 standard version V1.0" (http://emi3group.com/documents-links/) "Part 2: business objects."
    contract_id = models.CharField(max_length=36)

    # Visual readable number/identification as printed on the Token (RFID card), might be equal to the contract_id.
    visual_number = models.CharField(max_length=64, null=True, blank=True)

    # Issuing company, most of the times the name of the company printed on the token (RFID card),
    # not necessarily the eMSP.
    issuer = models.CharField(max_length=64)

    # This ID groups a couple of tokens. This can be used to make two or more tokens work as one,
    # so that a session can be started with one token and stopped with another, handy when a card and key-fob
    # are given to the EV-driver. Beware that OCPP 1.5/1.6 only support group_ids
    # (it is called parentId in OCPP 1.5/1.6) with a maximum length of 20.
    group_id = models.CharField(max_length=36, null=True, blank=True)

    valid = models.BooleanField()

    ALWAYS = 'ALWAYS'
    ALLOWED_OFFLINE = 'ALLOWED_OFFLINE'
    NEVER = 'NEVER'

    WHITELIST_CHOICES = (
        # Token always has to be whitelisted, realtime authorization is not possible/allowed.
        # CPO shall always allow any use of this Token.
        (ALWAYS, 'Always'),

        # It is allowed to whitelist the token, realtime authorization is also allowed.
        # The CPO may choose which version of authorization to use.
        (ALLOWED, 'Allowed'),

        # In normal situations realtime authorization shall be used. But when the CPO cannot get a response
        # from the eMSP (communication between CPO and eMSP is offline), the CPO shall allow this Token to be used.
        (ALLOWED_OFFLINE, 'Allowed when offline'),

        # Whitelisting is forbidden, only realtime authorization is allowed. CPO shall always send
        # a realtime authorization for any use of this Token to the eMSP.
        (NEVER, 'Never, only real time'),
    )
    whitelist = models.CharField(max_length=15, choices=WHITELIST_CHOICES)

    # Language Code ISO 639-1. This optional field indicates the Token owner’s preferred interface language.
    # If the language is not provided or not supported then the CPO is free to choose its own language.
    language = models.CharField(max_length=2, null=True, blank=True)

    # The default Charging Preference. When this is provided, and a charging session is started on
    # an Charge Point that support Preference base Smart Charging and support this ProfileType,
    # the Charge Point can start using this ProfileType, without this having to be set via: Set Charging Preferences.
    PROFILE_TYPE_CHOICES = (
        ('CHEAP', 'Cheap charging'),  # Driver wants to use the cheapest charging profile possible.
        ('FAST', 'Fast charging'),  # Driver wants his EV charged as quickly as possible and is willing to pay a premium for this.
        ('GREEN', 'Green energy'),  # Driver wants his EV charged with as much regenerative (green) energy as possible.
        ('REGULAR', 'Regular, no preference'),  # Driver does not have special preferences.
    )
    default_profile_type = models.CharField(max_length=7, null=True, blank=True, choices=PROFILE_TYPE_CHOICES)

    # energy_contract = models.CharField(max_length=80)  # No type documentation available

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.party_id}: {self.type} {self.uid}'

    def save(self, *args, **kwargs):
        if hasattr(self, 'upper_case_fields'):
            for field in self.upper_case_fields:
                f = self.__getattribute__(field)
                if f:
                    upper_value = f.upper()
                    self.__setattr__(field, upper_value)
        return super(self.__class__, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('token-by-id', args=[self.country_code, self.party_id, self.uid])


class AuthorizationInfo(models.Model, ModelUtilMixin):

    # Status of the Token, and whether charging is allowed at the optionally given location.
    ALLOWED_CHOICES = (
        ('ALLOWED', 'Allowed'),
        ('BLOCKED', 'Blocked'),
        ('EXPIRED', 'Expired token'),
        ('NO_CREDIT', 'User has ho credit'),
        ('NOT_ALLOWED', 'Not allowed'),
    )
    allowed = models.CharField(max_length=11, choices=ALLOWED_CHOICES)

    # The complete Token object for which this authorization was requested.
    token = models.ForeignKey(Token, on_delete=models.PROTECT)

    # Optional reference to the location if it was included in the request, and if the EV driver is allowed
    # to charge at that location. Only the EVSEs the EV driver is allowed to charge at are returned.
    # location = models.ForeignKey(Location, on_delete=models.PROTECT)

    # Reference to the authorization given by the eMSP, when given, this reference will be provided
    # in the relevant Session and/or CDR.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    last_updated = models.DateTimeField(auto_now=True)

# Todo: OCPI tariff_id has to contain a valid OCHP tariffId (NLEVNT12345ABC)


class Tariff(models.Model, ModelUtilMixin, OcpiModule):

    ocpi_serializer_class = 'ocpi22.api.TariffSerializer'
    ocpi_module_name = Ocpi.Modules.TARIFFS

    class Meta:
        unique_together = [['country_code', 'party_id', 'uid']]

    upper_case_fields = ('country_code', 'party_id', 'currency')

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Tariff (following the ISO-15118 standard)
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the tariff within the CPO’s platform (and suboperator platforms)
    uid = models.CharField(max_length=36)

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(max_length=3)

    # Defines the type of the tariff. This allows for distinction in case of given Charging Preferences.
    # When omitted, this tariff is valid for all sessions.
    TYPE_CHOICES = (
        # Used to describe that a Tariff is valid when ad-hoc payment is used at
        # the Charge Point (for example: Debit or Credit card payment terminal).
        ('AD_HOC_PAYMENT', 'Ad hoc payment'),

        # Used to describe that a Tariff is valid when Charging Preference: CHEAP is set for the session.
        ('PROFILE_CHEAP', 'CHEAP profile'),

        # Used to describe that a Tariff is valid when Charging Preference: FAST is set for the session.
        ('PROFILE_FAST', 'FAST profile'),

        # Used to describe that a Tariff is valid when Charging Preference: GREEN is set for the session.
        ('PROFILE_GREEN', 'GREEN profile'),

        # Used to describe that a Tariff is valid when using an RFID, without any Charging Preference,
        # or when Charging Preference: REGULAR is set for the session.
        ('REGULAR', 'Regular profile'),
    )

    type = models.CharField(max_length=14, choices=TYPE_CHOICES, default='REGULAR')

    # URL to a web page that contains an explanation of the tariff information in human readable form.
    tariff_alt_url = models.URLField(blank=True, default='')

    # When this field is set, a Charging Session with this tariff will at least cost this amount.
    # This is different from a FLAT fee (Start Tariff, Transaction Fee), as a FLAT fee is
    # a fixed amount that has to be paid for any Charging Session.
    # A minimum price indicates that when the cost of a Charging Session is lower than this amount,
    # the cost of the Session will be equal to this amount. (Also see note below)

    # min_price
    # max_price

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs) -> None:
        if hasattr(self, 'upper_case_fields'):
            for field in self.upper_case_fields:
                f = self.__getattribute__(field)
                if f:
                    upper_value = f.upper()
                    self.__setattr__(field, upper_value)
        super(self.__class__, self).save(*args, **kwargs)

    def __str__(self):
        return self.uid

    def price(self):
        """Format the price components in a readable form"""
        # noinspection PyUnresolvedReferences
        components = [
            str(pc)
            for pc in [
                element
                for element in self.tariff_elements.all()
            ]
        ]
        # noinspection PyUnresolvedReferences
        return f"{' + '.join(components or [f'{self.uid}'])} -- {self.get_type_display()}"

    def link(self):
        url = reverse('admin:ocpi22_tariff_change', args=[self.pk])
        # noinspection PyUnresolvedReferences
        return format_html(
            f"<a href='{url}'>{self.price()} -- {self.get_type_display()}</a>"
        )

    def get_absolute_url(self):
        return reverse('tariff-by-id', args=[self.country_code, self.party_id, self.uid])


class TariffElement(models.Model, ModelUtilMixin):
    tariff = models.ForeignKey(Tariff, related_name='tariff_elements', on_delete=models.CASCADE)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return ", ".join([str(pc) for pc in self.price_components.all()])


class PriceComponent(models.Model, ModelUtilMixin):
    # List of price components that describe the pricing of a tariff.

    TYPE_CHOICES = (
        # Defined in kWh, step_size multiplier: 1 Wh
        ('ENERGY', 'Wh'),

        # Flat fee without unit for step_size
        ('FLAT', 'Flat'),

        # Time not charging: defined in hours, step_size multiplier: 1 second
        # ('PARKING_TIME', 'Parking seconds'),
        # Todo: Implement PARKING_TIME PriceComponent

        # Time charging: defined in hours, step_size multiplier: 1 second
        # Can also be used in combination with a RESERVATION restriction to describe the price of the reservation time.
        ('TIME', 'Charging seconds'),
    )
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)

    # Price /unit (excl. VAT) for this tariff dimension.
    price = models.FloatField()

    # Applicable VAT percentage for this tariff dimension. If omitted, no VAT is applicable.
    # Not providing a VAT is different from 0% VAT, which would be a value of 0.0 here.
    vat = models.FloatField(blank=True, null=True)

    # Minimum amount to be billed. This unit will be billed in this step_size blocks.
    # Amounts that are less then this step_size are rounded up to the given step_size.
    # For example: if type is TIME and step_size has a value of 300, then time will be billed in blocks of 5 minutes.
    # If 6 minutes were used, 10 minutes (2 blocks of step_size) will be billed.
    step_size = models.IntegerField()

    @property
    def tariff(self):
        return self.tariff_element.tariff

    tariff_element = models.ForeignKey(TariffElement, related_name='price_components', on_delete=models.CASCADE)

    def _format_step_and_type(self):
        t = self.type
        s = self.step_size
        if t == 'ENERGY':
            if s == 1000:
                return '/ kWh'
            else:
                return f'/ {s} Wh'
        elif t == 'FLAT':
            return 'flat'
        elif t == 'TIME':
            if s == 60:
                return '/ minute'
            elif s == 3600:
                return '/ hour'
            else:
                return f'/ {s} seconds'
        elif t == 'PARKING_TIME':
            if s == 60:
                return '/ parking minute'
            elif s == 3600:
                return '/ hour parking'
            else:
                return f'/ {s} parking seconds'
        # noinspection PyUnresolvedReferences
        return f'/ {s} {self.get_type_display()}'

    @staticmethod
    def _pretty_currency(c):
        return dict(EUR='€', GBP='£', USD='$').get(c, c)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.price or 0.0:.2f}{self._pretty_currency(self.tariff.currency)} {self._format_step_and_type()}'


class Facility(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'facilities'
    name = models.CharField(max_length=15)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


class Capability(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'capabilities'
    name = models.CharField(max_length=32)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


class Location(models.Model, ModelUtilMixin, OcpiModule):
    """
    A physical location with one or more EVSEs
    """

    ocpi_serializer_class = 'ocpi22.location.LocationSerializer'
    ocpi_module_name = Ocpi.Modules.LOCATIONS

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='party_uid'),
            models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    upper_case_fields = ['postal_code', 'country', 'country_code', 'party_id']

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Location (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the location within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=36)

    # Defines if a Location may be published on an website or app etc.
    # When this is set to false, only tokens identified in the field:
    # publish_allowed_to are allowed to be shown this Location.
    # When the same location has EVSEs that may be published and may not be published,
    # two 'Locations' should be created.
    publish = models.BooleanField(default=True)

    # Defines the set of values that identify a token to which a Location might be published.
    # At least one of the following fields SHALL be set: uid, visual_number, or group_id.
    #
    # When uid is set, type SHALL also be set.
    publish_allowed_to = models.ManyToManyField(Token, related_name='locations', blank=True)

    # Display name of the location
    name = models.CharField(max_length=255, blank=True)

    # Street/block name and house number if available.
    address = models.CharField(max_length=45)

    # City or town
    city = models.CharField(max_length=45)

    # Postal code of the location, may only be omitted when the location has no postal code:
    # in some countries charging locations at highways don’t have postal codes.
    postal_code = models.CharField(max_length=45, blank=True)

    # State or province of the location, only to be used when relevant
    state = models.CharField(max_length=20, blank=True)

    # ISO 3166-1 alpha-3 code for the country of this location
    country = models.CharField(max_length=3)

    # This class defines the geo location of the Charge Point. The geodetic system to be used is WGS 84.
    latitude = models.FloatField()
    longitude = models.FloatField()

    def get_coordinates(self):
        """Formatting for OCPI (2.2)"""
        return dict(latitude=self.latitude, longitude=self.longitude)

    def set_coordinates(self, value):
        ic()
        ic(value)
        raise NotImplementedError()

    coordinates = property(get_coordinates, set_coordinates)

    # An index for fast lookup, first 4 digits from lat
    lat_partition = models.SmallIntegerField(db_index=True, null=True, blank=True)
    # An index for fast lookup, first 4 digits from long
    long_partition = models.SmallIntegerField(db_index=True, null=True, blank=True)

    # Geographical location of related points relevant to the user
    # related_locations

    # The general type of parking at the charge point location
    PARKING_CHOICES = (
        ('ALONG_MOTORWAY', 'Along a motorway'),
        ('PARKING_GARAGE', 'In a parking garage'),
        ('PARKING_LOT', 'On a parking lot'),
        ('ON_DRIVEWAY', 'On a driveway'),
        ('ON_STREET', 'On the street'),
        ('UNDERGROUND_GARAGE', 'In an underground garage'),
    )
    parking_type = models.CharField(max_length=18, null=True, blank=True, choices=PARKING_CHOICES)

    # List of EVSEs that belong to this Location
    # evses (comes automatically from Evse class)

    # Human-readable directions on how to reach the location
    # directions

    operator = models.ForeignKey(BusinessDetails, related_name='operator_locations',
                                 null=True, blank=True, on_delete=models.PROTECT)
    suboperator = models.ForeignKey(BusinessDetails, related_name='suboperator_locations',
                                    null=True, blank=True, on_delete=models.PROTECT)
    owner = models.ForeignKey(BusinessDetails, related_name='owner_locations',
                              null=True, blank=True, on_delete=models.PROTECT)

    # Optional list of facilities this charging location directly belongs to
    facilities = models.ManyToManyField(Facility, related_name='facility_locations', blank=True)

    # Todo: get time zone based on coordinates
    # One of IANA tzdata’s TZ-values representing the time zone of the location.
    # Examples: "Europe/Oslo", "Europe/Zurich". (http://www.iana.org/time-zones)
    time_zone = models.CharField(max_length=64)

    # The times when the EVSEs at the location can be accessed for charging
    # opening_times

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name}, {self.address}, {self.city}' or f'[No name, UID: {self.pk}]'

    def save(self, *args, **kwargs):
        if hasattr(self, 'upper_case_fields'):
            for field in self.upper_case_fields:
                f = self.__getattribute__(field)
                if f:
                    upper_value = f.upper()
                    self.__setattr__(field, upper_value)
        return super(self.__class__, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('location-by-id', args=[self.country_code, self.party_id, self.uid])

    def get_quick_url(self):
        return reverse('quick-location-by-id', args=[self.uid])

    def street_address(self):
        return f'{self.address}, {self.postal_code} {self.city}, {self.state} {self.country}'

    def evse_count(self):
        # noinspection PyUnresolvedReferences
        return self.evses.count()

    def evse_list(self):
        # noinspection PyUnresolvedReferences
        return format_html(
            '<hr style="margin: 4px">'.join(
                [
                    f'<a href="{reverse("admin:ocpi22_evse_change", args=[e.pk])}">{str(e)}</a>'
                    for e in self.evses.all()
                ]
            )
        )


uid_validator = RegexValidator(r'^[0-9a-zA-Z\*\-]+$', message='Numbers and letters only')


class Evse(models.Model, ModelUtilMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'location'], name='evse_party_uid'),
        ]

    # Uniquely identifies the EVSE within the CPOs platform (and suboperator platforms).
    # For example a database ID or the actual "EVSE ID". This field can never be changed, modified or renamed.
    # This is the 'technical' identification of the EVSE, not to be used as 'human readable' identification,
    # use the field evse_id for that.
    # This field is named uid instead of id, because id could be confused with evse_id which is an eMI3 defined field.
    uid = models.CharField(max_length=36, validators=[uid_validator])

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    # Optional because: if an evse_id is to be re-used in the real world,
    # the evse_id can be removed from an EVSE object if the status is set to REMOVED.

    evse_id = models.CharField(max_length=48, blank=True, default='')

    # @property
    # def evse_id(self):
    #     # The eMI3 1.0 standard ID
    #     return f'{self.location.country_code}*{self.location.party_id}*E{self.location.uid}*{self.uid}'.upper()

    # Indicates the current status of the EVSE
    STATUS_CHOICES = (
        ('AVAILABLE', 'Available'),
        ('BLOCKED', 'Physically blocked'),
        ('CHARGING', 'Charging'),
        ('INOPERATIVE', 'Inoperative (not yet active or it is no longer available)'),
        ('OUTOFORDER', 'Out of order'),
        ('PLANNED', 'Planned, will be operating soon'),
        ('REMOVED', 'Discontinued/removed'),
        ('RESERVED', 'Reserved for a particular EV driver'),
        ('UNKNOWN', 'No status information available (also used when offline)'),
    )
    status = models.CharField(max_length=11, choices=STATUS_CHOICES)

    CAPABILITY_CHOICES = (
        ('CHARGING_PROFILE_CAPABLE', 'The EVSE supports charging profiles'),
        ('CHARGING_PREFERENCES_CAPABLE', 'The EVSE supports charging preferences'),
        ('CHIP_CARD_SUPPORT', 'EVSE has a payment terminal that supports chip cards'),
        ('CONTACTLESS_CARD_SUPPORT', 'EVSE has a payment terminal that supports contactless cards'),
        ('CREDIT_CARD_PAYABLE', 'EVSE has a payment terminal that makes it possible to pay for charging using a credit card'),
        ('DEBIT_CARD_PAYABLE', 'EVSE has a payment terminal that makes it possible to pay for charging using a debit card'),
        ('PED_TERMINAL', 'EVSE has a payment terminal with a pin-code entry device'),
        ('REMOTE_START_STOP_CAPABLE', 'The EVSE can remotely be started / stopped'),
        ('RESERVABLE', 'The EVSE can be reserved'),
        ('RFID_READER', 'Charging at this EVSE can be authorized with an RFID token'),
        ('TOKEN_GROUP_CAPABLE', 'This EVSE supports token groups, two or more tokens work as one'),
        ('UNLOCK_CAPABLE', 'Connectors can be unlocked remotely'),
    )
    capabilities = models.ManyToManyField(Capability, related_name='evses')

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='evses')

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.evse_id

    def connector_list(self):
        # noinspection PyUnresolvedReferences
        return format_html('<hr style="margin: 4px">'.join([f'{str(c)}<br>{c.tariff()}' for c in self.connectors.all()]))

    def get_absolute_url(self):
        return reverse('location-by-evse-id',
                       args=[self.location.country_code, self.location.party_id, self.location.uid, self.uid])

    def get_cpo_url(self):
        return reverse('cpo-evse-by-id',
                       args=[self.uid])

    def get_status_url(self):
        return reverse('cpo-evse-by-id',
                       args=[self.uid])


class Connector(models.Model, ModelUtilMixin):
    # Identifier of the Connector within the EVSE. Two Connectors may have the same id
    # as long as they do not belong to the same EVSE object.

    class Meta:
        unique_together = [['evse', 'uid']]

    uid = models.CharField(max_length=36)

    evse = models.ForeignKey(Evse, on_delete=models.CASCADE, related_name='connectors')

    STANDARD_CHOICES = (
        ('IEC_62196_T2', 'Type 2 "Mennekes"'),
        ('IEC_62196_T2_COMBO', 'CCS type 2'),
        ('CHADEMO', 'CHAdeMO'),
        ('IEC_62196_T1', 'IEC 62196 Type 1 "SAE J1772"'),
        ('IEC_62196_T1_COMBO', 'CCS type 1'),
        ('IEC_62196_T3A', 'IEC 62196 Type 3A'),
        ('IEC_62196_T3C', 'IEC 62196 Type 3C "Scame"'),
        ('DOMESTIC_A', 'Type "A", NEMA 1-15, 2 pins'),
        ('DOMESTIC_B', 'Type "B", NEMA 5-15, 3 pins'),
        ('DOMESTIC_C', 'Type "C", CEE 7 / 17, 2 pins'),
        ('DOMESTIC_D', 'Type "D", 3 pin'),
        ('DOMESTIC_E', 'Type "E", CEE 7 / 5 3 pins'),
        ('DOMESTIC_F', 'Type "F", CEE 7 / 4, Schuko, 3 pins'),
        ('DOMESTIC_G', 'Type "G", BS 1363, Commonwealth, 3 pins'),
        ('DOMESTIC_H', 'Type "H", SI-32, 3 pins'),
        ('DOMESTIC_I', 'Type "I", AS 3112, 3 pins'),
        ('DOMESTIC_J', 'Type "J", SEV 1011, 3 pins'),
        ('DOMESTIC_K', 'Type "K", DS 60884-2-D1, 3 pins'),
        ('DOMESTIC_L', 'Type "L", CEI 23-16-VII, 3 pins'),
        ('IEC_60309_2_single_16', 'IEC 60309-2 single phase 16 A (blue)'),
        ('IEC_60309_2_three_16', 'IEC 60309-2 three phase 16 A (red)'),
        ('IEC_60309_2_three_32', 'IEC 60309-2 three phase 32 A (red)'),
        ('IEC_60309_2_three_64', 'IEC 60309-2 three phase 64 A (red)'),
        ('PANTOGRAPH_BOTTOM_UP', 'On-board Bottom-up-Pantograph'),
        ('PANTOGRAPH_TOP_DOWN', 'Off-board Top-down-Pantograph'),
        ('TESLA_R', 'Tesla "Roadster"-type'),
        ('TESLA_S', 'Tesla "Model-S"-type'),
    )
    standard = models.CharField(max_length=21, choices=STANDARD_CHOICES)

    FORMAT_CHOICES = (
        ('SOCKET', 'Socket, bring your own cable'),
        ('CABLE', 'Cable included'),
    )
    format = models.CharField(max_length=6, choices=FORMAT_CHOICES)

    POWERTYPES = dict(
        CHADEMO='DC',
        IEC_62196_T2_COMBO='DC',
        IEC_62196_T2='AC_3_PHASE'
    )
    POWERTYPE_CHOICES = (
        ('AC_1_PHASE', 'AC 1-phase'),
        ('AC_3_PHASE', 'AC 3-phase'),
        ('DC', 'DC')
    )
    power_type = models.CharField(max_length=10, choices=POWERTYPE_CHOICES)

    max_voltage = models.SmallIntegerField()
    max_amperage = models.SmallIntegerField()
    max_electric_power = models.IntegerField(null=True, blank=True)

    tariff_ids = models.ManyToManyField(Tariff, related_name='tariffs', blank=True)

    terms_and_conditions = models.URLField(blank=True, default='')

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.power()} {self.get_standard_display()}'

    def power(self):
        return f'{int((self.max_electric_power or self.max_voltage * self.max_amperage) / 1000)} kW'

    def tariff(self):
        return format_html('<br>'.join([t.link() for t in self.tariff_ids.all()]))


class Session(models.Model, ModelUtilMixin, OcpiModule):
    """
    The Session object describes one charging session. That doesn’t mean it is required that energy
    has been transferred between EV and the Charge Point. It is possible that the EV never took energy
    from the Charge Point because it was instructed not to take energy by the driver.
    But as the EV was connected to the Charge Point, some form of start tariff,
    park tariff or reservation cost might be relevant.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id', 'country_code'], name='session_party_id_uid_country_code'),
            # models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    ocpi_module_name = Ocpi.Modules.SESSIONS
    ocpi_serializer_class = 'ocpi22.api.SessionSaveSerializer'

    # ISO-3166 alpha-2 country code of the CPO that owns this Session
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Session (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # The unique id that identifies the charging session in the CPO platform.
    uid = models.CharField(max_length=36)

    # The timestamp when the session became ACTIVE in the Charge Point.
    # When the session is still PENDING, this field SHALL be set to the time the Session was
    # created at the Charge Point.
    # Todo: When a Session goes from PENDING to ACTIVE, this field SHALL be update to the moment the Session went to ACTIVE in the Charge Point.
    start_date_time = models.DateTimeField()

    # The timestamp when the session was completed/finished, charging might have finished before the session ends,
    # for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField(blank=True, null=True)

    # How many kWh were charged.
    kwh = models.FloatField()

    # Token used to start this charging session, including all the relevant information to identify the unique token.
    # Unique ID by which this Token can be identified.
    # This is the field used by the CPO’s system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a type=APP_USER Token, it will be a unique, by the eMSP, generated ID.
    cdr_token_uid = models.CharField(max_length=36)

    # Type of the token
    cdr_token_type = models.CharField(max_length=11, choices=Token.TYPE_CHOICES)

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    cdr_token_contract_id = models.CharField(max_length=36)

    AUTH_REQUEST = 'AUTH_REQUEST'
    COMMAND = 'COMMAND'
    WHITELIST = 'WHITELIST'

    AUTH_METHOD_CHOICES = (
        # Authentication request has been sent to the eMSP.
        (AUTH_REQUEST, 'Authentication request to eMSP'),

        # Command like StartSession or ReserveNow used to start the Session,
        # the Token provided in the Command was used as authorization.
        (COMMAND, 'Command from eMSP'),

        # Whitelist used for authentication, no request to the eMSP has been performed.
        (WHITELIST, 'Token on whitelist'),
    )

    # Method used for authentication.
    auth_method = models.CharField(max_length=12, choices=AUTH_METHOD_CHOICES)

    # Reference to the authorization given by the eMSP. Todo: When the eMSP provided an authorization_reference in either:
    # Todo: real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    # Location.id of the Location object of this CPO, on which the charging session is/was happening.
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='sessions')

    # EVSE.uid of the EVSE of this Location on which the charging session is/was happening.
    evse = models.ForeignKey(Evse, on_delete=models.PROTECT, related_name='sessions')

    # Connector.id of the Connector of this Location the charging session is/was happening.
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT, related_name='sessions', blank=True, null=True)

    # Optional identification of the kWh meter.
    meter_id = models.CharField(max_length=255, blank=True, null=True)

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(max_length=3)

    # The total cost of the session in the specified currency. This is the price that the eMSP will
    # have to pay to the CPO. A total_cost of 0.00 means free of charge. When omitted, i.e. no price
    # information is given in the Session object, it does not imply the session is/was free of charge.
    total_cost_excl_vat = models.FloatField(blank=True, null=True)
    total_cost_incl_vat = models.FloatField(blank=True, null=True)

    @property
    def total_cost(self):
        # I firmly believe this is not in use
        raise NotImplementedError()
        # For SessionSaveSerializer, OCPI 2.2 format
        return get_total_cost(self)

    # The status of this session
    STATUS_CHOICES = (
        # The session has been accepted and is active. All pre-conditions were met: Communication between EV and EVSE
        # (for example: cable plugged in correctly), EV or driver is authorized. EV is being charged,
        # or can be charged. Energy is, or is not, being transfered.
        ('ACTIVE', 'Active'),

        # The session has been finished successfully.
        # Todo: No more modifications will be made to the Session object using this state.
        ('COMPLETED', 'Completed'),

        # The Session object using this state is declared invalid and will not be billed.
        ('INVALID', 'Invalid'),

        # The session is pending, it has not yet started. Not all pre-conditions are met.
        # This is the initial state. The session might never become an active session.
        ('PENDING', 'Pending'),

        # The session is started due to a reservation, charging has not yet started.
        # The session might never become an active session.
        ('RESERVATION', 'Reservation'),
    )
    status = models.CharField(max_length=11, choices=STATUS_CHOICES, default='PENDING')

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def calculate_price(self) -> (float, float):
        connector = self.connector
        kwh: float = float(self.kwh)
        hours = (self.end_date_time - self.start_date_time).seconds / 3600
        result_incl_vat: float = 0.0
        result_excl_vat: float = 0.0
        tariff: Tariff

        for tariff in connector.tariff_ids.all():
            if tariff.type != 'REGULAR':
                # Todo: Implement profile types
                continue
            pc: PriceComponent
            # noinspection PyUnresolvedReferences
            for pc in tariff.price_components.all():
                excl_vat = dict(
                    ENERGY=lambda x: kwh * x,
                    TIME=lambda x: hours * x,
                    FLAT=lambda x: x
                ).get(pc.type, lambda x: 0.0)(pc.price)
                incl_vat = excl_vat * (1.0 + pc.vat / 100) \
                    if pc.vat else excl_vat
                ic(pc, excl_vat)
                result_incl_vat += incl_vat
                result_excl_vat += excl_vat
        self.total_cost_incl_vat = round(result_incl_vat, 2)
        self.total_cost_excl_vat = round(result_excl_vat, 2)

    def __str__(self):
        return f'{self.cdr_token_uid} - {self.start_date_time} - {self.kwh}kWh - ' \
               f'EVSE {self.evse.evse_id} - ' \
               f'{self.connector.get_standard_display() if self.connector else "no connector"}'

    def get_absolute_url(self):
        return reverse('session-by-id', args=[self.country_code, self.party_id, self.uid])

    def total_time(self):
        if self.status == 'INVALID':
            return '-'
        end = self.end_date_time if self.end_date_time else timezone.now()
        return hours_minutes((end - self.start_date_time).seconds/3600)

    def cost(self) -> str:
        cost_format = "{incl_vat} ({excl_vat}) {currency}"
        if not self.total_cost_excl_vat and not self.total_cost_incl_vat:
            return 'N/A'
        if self.total_cost_incl_vat:
            cost_format = "{incl_vat} {currency}"
        else:
            cost_format = "{excl_vat} {currency} (VAT 0%)"

        return cost_format.format(incl_vat=self.total_cost_incl_vat,
                                  excl_vat=self.total_cost_excl_vat,
                                  currency=self.currency)

# Todo: CDR.id must contain the CPO-ID (NLEVN12345ABCDEFG...) [up to 36 characters total]
# Todo: CDR.id must follow the pattern: Regular Expression: [0-9A-Z]{1,36}


class Cdr(models.Model, ModelUtilMixin):
    """
    A Charge Detail Record is the description of a concluded charging session.
    The CDR is the only billing-relevant object. CDRs are sent from the CPO to the eMSP
    after the charging session has ended. Although there is no requirement to send CDRs in (semi-) realtime,
    it is seen as good practice to send them as soon as possible. But if there is an agreement between
    parties to send them, for example, once a month, that is also allowed by OCPI.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='cdr_party_uid'),
            # Todo: models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    # ISO-3166 alpha-2 country code of the CPO that owns this CDR
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this CDR (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the CDR within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=39)

    # Start timestamp of the charging session, or in-case of a reservation
    # (before the start of a session) the start of the reservation.
    start_date_time = models.DateTimeField()

    # The timestamp when the session was completed/finished, charging might have finished before
    # the session ends, for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField()

    # Unique ID of the Session for which this CDR is sent. Is only allowed to be omitted
    # when the CPO has not implemented the Sessions module or this CDR is the result of a reservation
    # that never became a charging session, thus no OCPI Session.
    session_id = models.CharField(max_length=36, blank=True, default='')

    # Token used to start this charging session, includes all the relevant information to identify the unique token.
    cdr_token_uid = models.CharField(max_length=36)

    # Type of the token
    cdr_token_type = models.CharField(max_length=11, choices=Token.TYPE_CHOICES)

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    cdr_token_contract_id = models.CharField(max_length=36)

    # Method used for authentication.
    auth_method = models.CharField(max_length=12, choices=Session.AUTH_METHOD_CHOICES)

    # Reference to the authorization given by the eMSP. When the eMSP provided an authorization_reference in either:
    # real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    # Location where the charging session took place, including only the relevant EVSE and Connector.
    # Uniquely identifies the location within the CPO’s platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    cdr_location_id = models.CharField(max_length=36)

    # Street/block name and house number if available.
    cdr_location_address = models.CharField(max_length=45)

    # City or town.
    cdr_location_city = models.CharField(max_length=45)

    # Postal code of the location.
    cdr_location_postal_code = models.CharField(max_length=10)

    # ISO 3166-1 alpha-3 code for the country of this location.
    cdr_location_country = models.CharField(max_length=3)

    # Coordinates of the location.
    cdr_location_latitude = models.CharField(max_length=10)
    cdr_location_longitude = models.CharField(max_length=11)

    # Uniquely identifies the EVSE within the CPO’s platform (and suboperator platforms).
    # For example a database unique ID or the actual EVSE ID. This field can never be changed, modified or renamed.
    # This is the technical identification of the EVSE, not to be used as human readable identification,
    # use the field: evse_id for that.
    cdr_location_evse_uid = models.CharField(max_length=36)

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects.".
    cdr_location_evse_id = models.CharField(max_length=48)

    # Identifier of the connector within the EVSE.
    cdr_location_connector_id = models.CharField(max_length=36)

    # The standard of the installed connector.
    cdr_location_connector_standard = models.CharField(max_length=21, choices=Connector.STANDARD_CHOICES)

    # The format (socket/cable) of the installed connector.
    cdr_location_connector_format = models.CharField(max_length=6, choices=Connector.FORMAT_CHOICES)

    # The power type of the connector (AC/DC, phases)
    cdr_location_connector_power_type = models.CharField(max_length=10, choices=Connector.POWERTYPE_CHOICES)

    # Currency of the CDR in ISO 4217 Code.
    currency = models.CharField(max_length=3)

    # List of relevant Tariff Elements, see: Tariff. When relevant, a Free of Charge tariff
    # should also be in this list, and point to a defined Free of Charge Tariff.
    tariffs = models.ManyToManyField(Tariff, blank=True)

    # Total sum of all the costs of this transaction in the specified currency.
    total_cost_excl_vat = models.FloatField()
    total_cost_incl_vat = models.FloatField(blank=True, null=True)

    # Total energy charged, in kWh.
    total_energy = models.FloatField()

    # Total duration of the charging session (including the duration of charging and not charging), in hours.
    total_time = models.FloatField()

    # When set to true, this is a Credit CDR, and the field credit_reference_id needs to be set as well.
    # Todo: Make a "create credit CDR" management command
    credit = models.BooleanField(default=False)
    credit_reference = models.ForeignKey('Cdr', blank=True, null=True, on_delete=models.PROTECT)

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.cdr_token_type} {self.cdr_token_uid} - {self.total_cost_incl_vat} {self.currency} - ' \
               f'{(self.total_time / 60.0):.4f} hours - {self.end_date_time}'

    def get_absolute_url(self):
        return reverse('cdr-detail', args=[self.uid])

    def total_cost(self):
        return f'{"-" if self.credit else ""}{self.total_cost_incl_vat:.2f}/' \
               f'{"-" if self.credit else ""}{self.total_cost_excl_vat:.2f} {self.currency}' \
               f'{" (credited)" if self.credit else ""}'

    def charging_time(self):
        return hours_minutes(self.total_time)


def calculate_partition(coordinate):
    if not coordinate:
        return 0
    return int(float(coordinate) * 100.0)


@receiver(pre_save, sender=Location)
def location_pre_save(sender, instance, *_args, **_kwargs):
    location: Location = instance
    location.lat_partition = calculate_partition(location.latitude)
    location.long_partition = calculate_partition(location.longitude)


@receiver(post_save)
def atomic_post_save(sender, instance, **kwargs):
    """
    This makes sure that updates are sent only once per atomic operation. There was a problem
    with post_save being triggered first when a new Location is saved, then again with Evses and Connectors.
    """
    if hasattr(instance, "atomic_post_save") and transaction.get_connection().in_atomic_block:
        transaction.on_commit(lambda: instance.atomic_post_save(**kwargs))


# Todo: Prevent creating EVSE linked to a Location owned by another party


@receiver(post_save, sender=Evse)
def evse_post_save(sender, instance, *_args, **kwargs):
    """
    Make sure that only Admin calls Evse.save() without the update_fields list
    """
    # ic()
    # ic(kwargs)
    update_fields = kwargs.get('update_fields', [])
    if update_fields and 'last_updated' in update_fields:
        # If only last_updated has been changed, Location.last_updated has been already updated by connector_post_save
        # ic('evse_post_save was triggered by connector_post_save, no updating for Location.last_updated')
        return
    # ic('evse_post_save is updating Location.last_updated')
    evse = instance
    evse.location.last_updated = evse.last_updated
    evse.location.save(update_fields=['last_updated'])
    # if location.country_code == settings.COUNTRY_CODE and location.party_id == settings.PARTY_ID:
    #     ic('*** This is our location, sending updates to all known parties')
    #     # from ocpi22.location import send_evse_updates
    #     # send_evse_updates(evse.uid)
    #     from ocpi22.location import send_location_updates
    #     send_location_updates(location)


@receiver(post_save, sender=Connector)
def connector_post_save(sender, instance, *_args, **kwargs):
    # ic()
    # ic(kwargs)
    connector: Connector = instance
    evse = connector.evse
    # ic('connector_post_save is updating Evse.last_updated')
    evse.last_updated = connector.last_updated
    evse.save(update_fields=['last_updated'])
    # ic('connector_post_save is updating Location.last_updated')
    location = connector.evse.location
    location.last_updated = connector.last_updated
    location.save(update_fields=['last_updated'])


@receiver(pre_save, sender=Connector)
def connector_pre_save(sender, instance, *_args, **_kwargs):
    connector: Connector = instance
    if not connector.uid:
        connector.uid = uuid.uuid4().hex
    if not connector.power_type:
        connector.power_type = Connector.POWERTYPES[connector.standard]


@receiver(pre_save, sender=Credentials)
def credentials_pre_save(sender, instance, *_args, **_kwargs):
    credentials: Credentials = instance
    if not credentials.token_a:
        credentials.token_a = generate_random_token()
    # if not credentials.ours:
    #     credentials.ours = generate_random_token()


@receiver(pre_save, sender=Tariff)
def tariff_pre_save(sender, instance, *_args, **_kwargs):
    tariff: Tariff = instance
    if not tariff.uid:
        tariff.uid = uuid.uuid4().hex


@receiver(post_save, sender=PriceComponent)
def price_component_post_save(sender, instance: PriceComponent, *_args, **_kwargs):
    tariff = instance.tariff
    tariff.last_updated = timezone.now()
    tariff.save()
