import os
import uuid

from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.html import format_html
from rest_framework.reverse import reverse

PARTY_ID = os.environ.get('PARTY_ID', 'XXX')
COUNTRY_CODE = os.environ.get('COUNTRY_CODE', 'XX')

AUTH_METHOD_CHOICES = (
    # Authentication request has been sent to the eMSP.
    ('AUTH_REQUEST', 'Authentication request to eMSP'),

    # Command like StartSession or ReserveNow used to start the Session,
    # the Token provided in the Command was used as authorization.
    ('COMMAND', 'Command from eMSP'),

    # Whitelist used for authentication, no request to the eMSP has been performed.
    ('WHITELIST', 'Token on whitelist'),
)


class Token(models.Model):
    """
    A Token structure with data owned by the eMSP
    """

    class Meta:
        unique_together = [['party_id', 'uid']]

    # ISO-3166 alpha-2 country code of the MSP that 'owns' this Token
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the MSP that 'owns' this Token (following the ISO-15118)
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Unique ID by which this Token can be identified.
    # This is the field used by CPO system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a APP_USER or AD_HOC_USER Token, it will be a uniquely, by the eMSP, generated ID.
    # This field is named uid instead of id to prevent confusion with: contract_id.
    uid = models.CharField(max_length=36)

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

    WHITELIST_CHOICES = (
        # Token always has to be whitelisted, realtime authorization is not possible/allowed.
        # CPO shall always allow any use of this Token.
        ('ALWAYS', 'Always'),

        # It is allowed to whitelist the token, realtime authorization is also allowed.
        # The CPO may choose which version of authorization to use.
        ('ALLOWED', 'Allowed'),

        # In normal situations realtime authorization shall be used. But when the CPO cannot get a response
        # from the eMSP (communication between CPO and eMSP is offline), the CPO shall allow this Token to be used.
        ('ALLOWED_OFFLINE', 'Allowed when offline'),

        # Whitelisting is forbidden, only realtime authorization is allowed. CPO shall always send
        # a realtime authorization for any use of this Token to the eMSP.
        ('NEVER', 'Never, only real time'),
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

    def get_absolute_url(self):
        return reverse('token-by-id', args=[self.country_code, self.party_id, self.uid])


class AuthorizationInfo(models.Model):

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
    authorization_reference = models.CharField(max_length=36)

    last_updated = models.DateTimeField(auto_now=True)


class Tariff(models.Model):
    class Meta:
        unique_together = [['party_id', 'uid']]
    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Tariff (following the ISO-15118 standard)
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the tariff within the CPO’s platform (and suboperator platforms)
    uid = models.CharField(max_length=36, default=uuid.uuid4())

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
    type = models.CharField(max_length=14, choices=TYPE_CHOICES)

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

    def __str__(self):
        # noinspection PyUnresolvedReferences
        components = [str(x) for x in self.price_components.all()]
        return ' + '.join(components or [f'{self.uid}'])

    def link(self):
        # noinspection PyUnresolvedReferences
        components = [str(x) for x in self.price_components.all()]
        url = reverse('admin:ocpi22_tariff_change', args=[self.pk])
        return format_html(
            f"<a href='{url}'>{' + '.join(components or [f'{self.uid}'])} -- {self.get_type_display()}</a>"
        )

    def get_absolute_url(self):
        return reverse('tariff-by-id', args=[self.country_code, self.party_id, self.uid])


class PriceComponent(models.Model):
    TYPE_CHOICES = (
        # Defined in kWh, step_size multiplier: 1 Wh
        ('ENERGY', 'Wh'),

        # Flat fee without unit for step_size
        ('FLAT', 'Flat'),

        # Time not charging: defined in hours, step_size multiplier: 1 second
        ('PARKING_TIME', 'Parking seconds'),

        # Time charging: defined in hours, step_size multiplier: 1 second
        # Can also be used in combination with a RESERVATION restriction to describe the price of the reservation time.
        ('TIME', 'Charging seconds'),
    )
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)

    # Price per unit (excl. VAT) for this tariff dimension.
    price = models.FloatField()

    # Applicable VAT percentage for this tariff dimension. If omitted, no VAT is applicable.
    # Not providing a VAT is different from 0% VAT, which would be a value of 0.0 here.
    vat = models.FloatField(blank=True, null=True)

    # Minimum amount to be billed. This unit will be billed in this step_size blocks.
    # Amounts that are less then this step_size are rounded up to the given step_size.
    # For example: if type is TIME and step_size has a value of 300, then time will be billed in blocks of 5 minutes.
    # If 6 minutes were used, 10 minutes (2 blocks of step_size) will be billed.
    step_size = models.IntegerField()

    tariff = models.ForeignKey(Tariff, related_name='price_components', on_delete=models.PROTECT)

    def _format_step_and_type(self):
        t = self.type
        s = self.step_size
        if t == 'ENERGY':
            if s == 1000:
                return '/ kWh'
            else:
                return f'/ {s} kWh'
        elif t == 'FLAT':
            return 'fixed'
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


class BusinessDetails(models.Model):
    class Meta:
        verbose_name_plural = 'business details'
    name = models.CharField(max_length=100)
    website = models.URLField(blank=True, default='')
    logo = models.URLField(blank=True, default='')

    def __str__(self):
        return self.name


class Facility(models.Model):
    class Meta:
        verbose_name_plural = 'facilities'
    name = models.CharField(max_length=15)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


class Capability(models.Model):
    class Meta:
        verbose_name_plural = 'capabilities'
    name = models.CharField(max_length=28)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


class Cdr(models.Model):
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
    uid = models.CharField(max_length=39, default=uuid.uuid4())

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
    cdr_token = models.ForeignKey(Token, on_delete=models.PROTECT)

    # Method used for authentication.
    auth_method = models.CharField(max_length=12, choices=AUTH_METHOD_CHOICES)

    # Location where the charging session took place, including only the relevant EVSE and Connector.
    cdr_location = models.TextField()

    # Currency of the CDR in ISO 4217 Code.
    currency = models.CharField(max_length=3)

    # List of relevant Tariff Elements, see: Tariff. When relevant, a Free of Charge tariff
    # should also be in this list, and point to a defined Free of Charge Tariff.
    tariffs = models.TextField()

    # Total sum of all the costs of this transaction in the specified currency.
    total_cost_excl_vat = models.FloatField()
    total_cost_inc_vat = models.FloatField()

    # Total energy charged, in kWh.
    total_energy = models.FloatField()

    # Total duration of the charging session (including the duration of charging and not charging), in hours.
    total_time = models.FloatField()

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.cdr_token} - {self.total_cost_inc_vat} {self.currency} - ' \
               f'{self.total_time/60} min - {self.end_date_time}'




class Location(models.Model):
    """
    A physical location with one or more EVSEs
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='party_uid'),
            models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Location (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the location within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=36, default=uuid.uuid4())

    # Defines if a Location may be published on an website or app etc.
    # When this is set to false, only tokens identified in the field:
    # publish_allowed_to are allowed to be shown this Location.
    # When the same location has EVSEs that may be published and may not be published,
    # two 'Locations' should be created.
    publish = models.BooleanField()

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

    def get_absolute_url(self):
        return reverse('location-by-id', args=[self.country_code, self.party_id, self.uid])


class Evse(models.Model):
    # Uniquely identifies the EVSE within the CPOs platform (and suboperator platforms).
    # For example a database ID or the actual "EVSE ID". This field can never be changed, modified or renamed.
    # This is the 'technical' identification of the EVSE, not to be used as 'human readable' identification,
    # use the field evse_id for that.
    # This field is named uid instead of id, because id could be confused with evse_id which is an eMI3 defined field.
    uid = models.CharField(max_length=36, default=uuid.uuid4())

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    # Optional because: if an evse_id is to be re-used in the real world,
    # the evse_id can be removed from an EVSE object if the status is set to REMOVED.

    @property
    def evse_id(self):
        return f'{self.location.country_code}*{self.location.party_id}*E{self.location.uid}*{self.uid}'

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

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='evses')

    last_updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.evse_id

    def connector_list(self):
        # noinspection PyUnresolvedReferences
        return format_html('<hr style="margin: 4px">'.join([f'{str(c)}<br>{c.tariff()}' for c in self.connectors.all()]))

    def get_absolute_url(self):
        return reverse('evse-by-id',
                       args=[self.location.country_code, self.location.party_id, self.location.uid, self.uid])

    def get_cpo_url(self):
        return reverse('evse-by-id-cpo',
                       args=[self.uid])


class Connector(models.Model):
    # Identifier of the Connector within the EVSE. Two Connectors may have the same id
    # as long as they do not belong to the same EVSE object.

    class Meta:
        unique_together = [['evse', 'uid']]

    uid = models.CharField(max_length=36, default=uuid.uuid4())

    evse = models.ForeignKey(Evse, on_delete=models.PROTECT, related_name='connectors')

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

    POWERTYPE_CHOICES = (
        ('AC_1_PHASE', 'AC 1-phase'),
        ('AC_3_PHASE', 'AC 3-phase'),
        ('DC', 'DC')
    )
    power_type = models.CharField(max_length=10, choices=POWERTYPE_CHOICES)

    max_voltage = models.SmallIntegerField()
    max_amperage = models.SmallIntegerField()
    max_electric_power = models.SmallIntegerField(null=True, blank=True)

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


class Session(models.Model):
    """
    The Session object describes one charging session. That doesn’t mean it is required that energy
    has been transferred between EV and the Charge Point. It is possible that the EV never took energy
    from the Charge Point because it was instructed not to take energy by the driver.
    But as the EV was connected to the Charge Point, some form of start tariff,
    park tariff or reservation cost might be relevant.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='session_party_id_uid'),
            # models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    # ISO-3166 alpha-2 country code of the CPO that owns this Session
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Session (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # The unique id that identifies the charging session in the CPO platform.
    uid = models.CharField(max_length=36, default=uuid.uuid4())

    # The timestamp when the session became ACTIVE in the Charge Point.
    # When the session is still PENDING, this field SHALL be set to the time the Session was
    # created at the Charge Point.
    # Todo: When a Session goes from PENDING to ACTIVE, this field SHALL be update to the moment the Session went to ACTIVE in the Charge Point.
    start_date_time = models.DateTimeField(default=timezone.now())

    # The timestamp when the session was completed/finished, charging might have finished before the session ends,
    # for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField(blank=True, null=True)

    # How many kWh were charged.
    kwh = models.FloatField()

    # Token used to start this charging session, including all the relevant information to identify the unique token.
    cdr_token = models.ForeignKey(Token, on_delete=models.PROTECT)

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
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT, related_name='sessions')

    # Optional identification of the kWh meter.
    meter_id = models.CharField(max_length=255, blank=True, null=True)

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(max_length=3)

    # The total cost of the session in the specified currency. This is the price that the eMSP will
    # have to pay to the CPO. A total_cost of 0.00 means free of charge. When omitted, i.e. no price
    # information is given in the Session object, it does not imply the session is/was free of charge.
    total_cost_excl_vat = models.FloatField(blank=True, null=True)
    total_cost_incl_vat = models.FloatField(blank=True, null=True)

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

    def __str__(self):
        return f'{self.cdr_token} - {self.start_date_time} - {self.kwh}kWh - ' \
               f'EVSE {self.evse.evse_id} - {self.connector.get_standard_display()}'

    def get_absolute_url(self):
        return reverse('session-by-id', args=[self.country_code, self.party_id, self.uid])

    # def get_cpo_url(self):
    #     return reverse('session-by-id-cpo', args=[self.uid])


def calculate_partition(coordinate):
    if not coordinate:
        return 0
    return int(float(coordinate) * 100.0)


@receiver(pre_save, sender=Location)
def my_callback(sender, instance, *_args, **_kwargs):
    location: Location = instance
    location.lat_partition = calculate_partition(location.latitude)
    location.long_partition = calculate_partition(location.longitude)
    # if not charger.costs():
    #     charger.access = 'FR'


@receiver(post_save, sender=Evse)
def my_callback(sender, instance, *_args, **_kwargs):
    evse = instance
    location = evse.location
    # location.last_updated = evse.last_updated
    location.save()


@receiver(post_save, sender=Connector)
def my_callback(sender, instance, *_args, **_kwargs):
    connector: Connector = instance
    evse = connector.evse
    # evse.last_updated = connector.last_updated
    evse.save()
