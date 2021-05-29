from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver


class Token(models.Model):
    """
    A Token structure with data owned by the eMSP
    """

    # ISO-3166 alpha-2 country code of the MSP that 'owns' this Token
    country_code = models.CharField(max_length=2)

    # CPO ID of the MSP that 'owns' this Token (following the ISO-15118)
    party_id = models.CharField(max_length=3)

    # Unique ID by which this Token can be identified.
    # This is the field used by CPO system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a APP_USER or AD_HOC_USER Token, it will be a uniquely, by the eMSP, generated ID.
    # This field is named uid instead of id to prevent confusion with: contract_id.
    uid = models.CharField(max_length=36)

    TYPE_CHOICES = (
        ('AD_HOC_USER', 'Ad hoc user'),
        ('APP_USER', 'Application user'),
        ('OTHER', 'Other'),
        ('RFID', 'RFID tag'),
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

    def __str__(self):
        return f'{self.party_id}: {self.uid} {self.type}'


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
    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2)

    # CPO ID of the CPO that 'owns' this Tariff (following the ISO-15118 standard)
    party_id = models.CharField(max_length=3)

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
        ('REGULAR', 'Regular'),
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

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return ' + '.join([str(x) for x in self.price_components.all()] or f'{self.uid}')


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
                return 'per kWh'
            else:
                return f'per {s} kWh'
        elif t == 'FLAT':
            return 'flat price'
        elif t == 'TIME':
            if s == 60:
                return 'per minute'
            else:
                return f'per {s} seconds'
        elif t == 'PARKING_TIME':
            if s == 60:
                return 'per parking minute'
            else:
                return f'per {s} parking seconds'
        return f'per {s} {self.get_type_display()}'

    def _pretty_currency(self, c):
        return dict(
            EUR='€',
            GBP='£',
            USD='$'
        ).get(c, c)

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
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Capability(models.Model):
    class Meta:
        verbose_name_plural = 'capabilities'
    name = models.CharField(max_length=28)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Location(models.Model):
    """
    A physical location with one or more EVSEs
    """

    unique_together = [
        ['uid', 'suboperator', 'operator'],
    ]

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2)

    # CPO ID of the CPO that 'owns' this Location (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3)

    # Uniquely identifies the location within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=36)

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

    # Todo: It is best practice to return the oldest (by creation date, not the last_updated field) first
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or str(self.pk)


class Evse(models.Model):
    # Uniquely identifies the EVSE within the CPOs platform (and suboperator platforms).
    # For example a database ID or the actual "EVSE ID". This field can never be changed, modified or renamed.
    # This is the 'technical' identification of the EVSE, not to be used as 'human readable' identification,
    # use the field evse_id for that.
    # This field is named uid instead of id, because id could be confused with evse_id which is an eMI3 defined field.
    uid = models.CharField(max_length=36)

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    # Optional because: if an evse_id is to be re-used in the real world,
    # the evse_id can be removed from an EVSE object if the status is set to REMOVED.
    evse_id = models.CharField(max_length=48)

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

    def __str__(self):
        return f'{self.uid} {self.evse_id}'


class Connector(models.Model):
    # Identifier of the Connector within the EVSE. Two Connectors may have the same id
    # as long as they do not belong to the same EVSE object.
    uid = models.CharField(max_length=36)

    evse = models.ForeignKey(Evse, on_delete=models.PROTECT, related_name='connectors')

    STANDARD_CHOICES = (
        ('CHADEMO', 'The connector type is CHAdeMO, DC'),
        ('DOMESTIC_A', 'Standard / Domestic household, type "A", NEMA 1-15, 2 pins'),
        ('DOMESTIC_B', 'Standard / Domestic household, type "B", NEMA 5-15, 3 pins'),
        ('DOMESTIC_C', 'Standard / Domestic household, type "C", CEE 7 / 17, 2 pins'),
        ('DOMESTIC_D', 'Standard / Domestic household, type "D", 3 pin'),
        ('DOMESTIC_E', 'Standard / Domestic household, type "E", CEE 7 / 5 3 pins'),
        ('DOMESTIC_F', 'Standard / Domestic household, type "F", CEE 7 / 4, Schuko, 3 pins'),
        ('DOMESTIC_G', 'Standard / Domestic household, type "G", BS 1363, Commonwealth, 3 pins'),
        ('DOMESTIC_H', 'Standard / Domestic household, type "H", SI-32, 3 pins'),
        ('DOMESTIC_I', 'Standard / Domestic household, type "I", AS 3112, 3 pins'),
        ('DOMESTIC_J', 'Standard / Domestic household, type "J", SEV 1011, 3 pins'),
        ('DOMESTIC_K', 'Standard / Domestic household, type "K", DS 60884-2-D1, 3 pins'),
        ('DOMESTIC_L', 'Standard / Domestic household, type "L", CEI 23-16-VII, 3 pins'),
        ('IEC_60309_2_single_16', 'IEC 60309-2 Industrial Connector single phase 16 amperes (usually blue)'),
        ('IEC_60309_2_three_16', 'IEC 60309-2 Industrial Connector three phase 16 amperes (usually red)'),
        ('IEC_60309_2_three_32', 'IEC 60309-2 Industrial Connector three phase 32 amperes (usually red)'),
        ('IEC_60309_2_three_64', 'IEC 60309-2 Industrial Connector three phase 64 amperes (usually red)'),
        ('IEC_62196_T1', 'IEC 62196 Type 1 "SAE J1772"'),
        ('IEC_62196_T1_COMBO', 'Combo Type 1 based, DC'),
        ('IEC_62196_T2', 'IEC 62196 Type 2 "Mennekes"'),
        ('IEC_62196_T2_COMBO', 'Combo Type 2 based, DC'),
        ('IEC_62196_T3A', 'IEC 62196 Type 3A'),
        ('IEC_62196_T3C', 'IEC 62196 Type 3C "Scame"'),
        ('PANTOGRAPH_BOTTOM_UP', 'On-board Bottom-up-Pantograph typically for bus charging'),
        ('PANTOGRAPH_TOP_DOWN', 'Off-board Top-down-Pantograph typically for bus charging'),
        ('TESLA_R', 'Tesla Connector "Roadster"-type (round, 4 pin)'),
        ('TESLA_S', 'Tesla Connector "Model-S"-type (oval, 5 pin)'),
    )
    standard = models.CharField(max_length=21, choices=STANDARD_CHOICES)

    FORMAT_CHOICES = (
        ('SOCKET', 'Socket, bring your own cable'),
        ('CABLE', 'The connector is an attached cable'),
    )
    format = models.CharField(max_length=6, choices=FORMAT_CHOICES)

    POWERTYPE_CHOICES = (
        ('AC_1_PHASE', 'AC 1-phase'),
        ('AC_3_PHASE', 'AC 3-phase'),
        ('DC', 'Direct Current')
    )
    power_type = models.CharField(max_length=10, choices=POWERTYPE_CHOICES)

    max_voltage = models.SmallIntegerField()
    max_amperage = models.SmallIntegerField()
    max_electric_power = models.SmallIntegerField(null=True, blank=True)

    tariff_ids = models.ManyToManyField(Tariff, related_name='tariffs', blank=True)

    terms_and_conditions = models.URLField(blank=True, default='')

    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.uid} {self.standard}'


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
