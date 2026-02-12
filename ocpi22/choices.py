from enum import Enum
from typing import Optional

import cachetools
import langcodes
import pytz
from django.conf import settings
from django.db import models
from django.utils import translation
from django.utils.translation import gettext_noop as _
from django.utils.translation import gettext_lazy as _lazy


class OcpiRolesEnum(Enum):
    CPO = "CPO"
    EMSP = "EMSP"
    HUB = "HUB"
    NAP = "NAP"
    NSP = "NSP"
    OTHER = "OTHER"
    PTP = "PTP"
    SCSP = "SCSP"
    UNKNO = "UNKNO"

    def __eq__(self, other):
        if isinstance(other, OcpiRolesEnum):
            return self.value == other.value
        elif isinstance(other, str):
            return self.value == other
        else:
            return False

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value

    def __hash__(self):
        return hash(self.value)


ROLE_CHOICES = (
    ("CPO", "Charge Point operator"),
    ("EMSP", "Emobility Service Provider"),
    ("HUB", "Hub"),
    ("NAP", "National Access Point"),
    ("NSP", "Navigation Service Provider"),
    ("OTHER", "Other"),
    ("PTP", "Payment Terminal Provider"),
    ("SCSP", "Smart Charging Service Provider"),
    (
        "UNKNO",
        "Unknown",
    ),  # This applies to parties behind a hub (NOT an OCPI specified role, just internal for us)
)

VERSION_CHOICES = (("22", "2.2"), ("221", "2.2.1"))
VERSION_CHOICES_DICT = dict(VERSION_CHOICES)

CONNECTED = "CONNECTED"
OFFLINE = "OFFLINE"
PLANNED = "PLANNED"
SUSPENDED = "SUSPENDED"

CONNECTION_STATUS_CHOICES = [
    (x, x.capitalize()) for x in (CONNECTED, OFFLINE, PLANNED, SUSPENDED)
]


class SessionStatus:
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    PENDING = "PENDING"
    RESERVATION = "RESERVATION"


class TokenType(str, Enum):
    AD_HOC_USER = "AD_HOC_USER"
    RFID = "RFID"
    APP_USER = "APP_USER"
    OTHER = "OTHER"


TOKEN_TYPE_CHOICES = [
    (TokenType.AD_HOC_USER.value, "Ad-hoc user"),
    (TokenType.RFID.value, "RFID"),
    (TokenType.APP_USER.value, "Application user"),
    (TokenType.OTHER.value, "Other"),
]


class OcpiModuleEnum(Enum):
    CREDENTIALS = "credentials"
    LOCATIONS = "locations"
    TOKENS = "tokens"
    COMMANDS = "commands"
    TARIFFS = "tariffs"
    CDRS = "cdrs"
    SESSIONS = "sessions"
    HUBCLIENTINFO = "hubclientinfo"
    PAYMENTS = "payments"

    def get_owner(self):
        return {
            self.LOCATIONS.value: OcpiRolesEnum.CPO,
            self.TOKENS.value: OcpiRolesEnum.EMSP,
            self.TARIFFS.value: OcpiRolesEnum.CPO,
            self.CDRS.value: OcpiRolesEnum.CPO,
            self.SESSIONS.value: OcpiRolesEnum.CPO,
            self.PAYMENTS.value: OcpiRolesEnum.PTP,
        }[self.value]

    def get_viewset(self):
        return {
            self.LOCATIONS.value: "ocpi22.locations.location.LocationViewSet",
            self.TOKENS.value: "ocpi22.ocpi.api.TokenViewSet",
            self.TARIFFS.value: "ocpi22.ocpi.api.TariffViewSet",
            self.CDRS.value: "ocpi22.ocpi.api.CdrViewSet",
            self.SESSIONS.value: "ocpi22.ocpi.api.SessionViewSet",
            self.PAYMENTS.value: "ocpi22.payments.api.TerminalViewSet",
        }[self.value]


IDENTIFIER_CHOICES = list(
    (module.value.lower(), module.value.capitalize()) for module in OcpiModuleEnum
)

ROLE_OPTIONS = ("CPO", "EMSP", "HUB", "NSP", "NAP", "PTP", "SCSP")


class EndpointRoleEnum(Enum):
    SENDER = "SENDER"
    RECEIVER = "RECEIVER"

    def __str__(self):
        return self.value


ENDPOINT_ROLE_CHOICES = (
    (EndpointRoleEnum.SENDER.value, "Sender"),
    (EndpointRoleEnum.RECEIVER.value, "Receiver"),
)


class OcppStatusChoices(models.TextChoices):
    AVAILABLE = "AVAILABLE", _("Available")
    PREPARING = "PREPARING", _("Preparing")
    CHARGING = "CHARGING", _("Charging")
    SUSPENDEDEV = "SUSPENDEDEV", _("Suspended by vehicle")
    SUSPENDEDEVSE = "SUSPENDEDEVSE", _("Suspended by charger")
    FINISHING = "FINISHING", _("Finishing")
    RESERVED = "RESERVED", _("Reserved")
    UNAVAILABLE = "UNAVAILABLE", _("Unavailable")
    FAULTED = "FAULTED", _("Out of order")


class CdrDimensionEnum(Enum):
    # Average charging current during this ChargingPeriod: defined in A (Ampere).
    # When negative, the current is flowing from the EV to the grid.
    CURRENT = "CURRENT"

    # Total amount of energy (dis-)charged during this ChargingPeriod: defined in kWh.
    # When negative, more energy was feed into the grid then charged into the EV. Default step_size is 1.
    ENERGY = "ENERGY"

    # Total amount of energy feed back into the grid: defined in kWh.
    ENERGY_EXPORT = "ENERGY_EXPORT"

    # Total amount of energy charged, defined in kWh.
    ENERGY_IMPORT = "ENERGY_IMPORT"

    # Sum of the maximum current over all phases, reached during this ChargingPeriod: defined in A (Ampere).
    MAX_CURRENT = "MAX_CURRENT"

    # Sum of the minimum current over all phases, reached during this ChargingPeriod,
    # when negative, current has flowed from the EV to the grid. Defined in A (Ampere).
    MIN_CURRENT = "MIN_CURRENT"

    # Maximum power reached during this ChargingPeriod: defined in kW (Kilowatt).
    MAX_POWER = "MAX_POWER"

    # Minimum power reached during this ChargingPeriod: defined in kW (Kilowatt),
    # when negative, the power has flowed from the EV to the grid.
    MIN_POWER = "MIN_POWER"

    # Time during this ChargingPeriod not charging: defined in hours, default step_size multiplier is 1 second.
    PARKING_TIME = "PARKING_TIME"

    # Average power during this ChargingPeriod: defined in kW (Kilowatt).
    # When negative,the power is flowing from the EV to the grid.
    POWER = "POWER"

    # Time during this ChargingPeriod Charge Point has been reserved and not yet been in use for this customer:
    # defined in hours, default step_size multiplier is 1 second.
    RESERVATION_TIME = "RESERVATION_TIME"

    # Current state of charge of the EV, in percentage, values allowed: 0 to 100. See note below.
    STATE_OF_CHARGE = "STATE_OF_CHARGE"

    # Time charging during this ChargingPeriod: defined in hours, default step_size multiplier is 1 second.
    TIME = "TIME"


CDR_DIMENSION_CHOICES = [
    (e.value, e.value.capitalize().replace("_", " ")) for e in CdrDimensionEnum
]


@cachetools.cached(cache={})
def _make_texts(english_text):
    result = []
    for language, _name in settings.LANGUAGES:
        with translation.override(language):
            if language == "en":
                tr = english_text
            else:
                tr = translation.gettext(english_text)
                if tr == english_text:
                    # No translation available
                    continue
            result.append(dict(language=language.upper(), text=tr))
    return result


class MessageTexts:
    @classmethod
    def get(cls, s, default=None):
        PREPARING_TO_CHARGE = _make_texts(_("Preparing to charge"))
        RESERVE_ACCEPTED = _make_texts(_("Charger is reserved for you"))
        STOPPING_TO_CHARGE = _make_texts(_("Stopping charging session"))
        # dict(language='FI', text='Latausta viimeistellään'),
        EVSE_OCCUPIED = _make_texts(_("The charger is currently in use"))
        # dict(language='FI', text='Latauspiste on parhaillaan käytössä'),
        DEFAULT_CHARGER_ERROR_TEXT = _make_texts(
            _("Unable to start charging at this time")
        )
        # dict(language='FI', text='Lataus ei ole mahdollista tällä hetkellä'),
        MS_CONNECTION_ERROR = _make_texts(
            _("Unable to connect to charge point management system")
        )
        # dict(language='FI', text='Yhteys latauspisteen hallintajärjestelmään on poikki'),
        NO_BALANCE = _make_texts(
            _("The token doesn't have enough balance on the account")
        )
        # dict(language='FI', text='Lataustilillä ei ole riittävästi katetta'),
        TOKEN_ACCEPTED = _make_texts(_("The token is accepted"))
        # dict(language='FI', text='Lataustunniste on hyväksytty'),
        TOKEN_NOT_VALID = _make_texts(_("Your token is no longer valid"))
        # dict(language='FI', text='Lataustunniste ei ole enää voimassa'),
        PROTOCOL_ERROR = _make_texts(
            _(
                "There is a communication error with one of the service provider internal systems"
            )
        )

        _texts = dict(
            START_ACCEPTED=PREPARING_TO_CHARGE,
            RESERVE_ACCEPTED=RESERVE_ACCEPTED,
            STOPPING_TO_CHARGE=STOPPING_TO_CHARGE,
            EVSE_OCCUPIED=EVSE_OCCUPIED,
            STOP_ACCEPTED=STOPPING_TO_CHARGE,
            DEFAULT_CHARGER_ERROR_TEXT=DEFAULT_CHARGER_ERROR_TEXT,
            MS_CONNECTION_ERROR=MS_CONNECTION_ERROR,
            NO_BALANCE=NO_BALANCE,
            TOKEN_ACCEPTED=TOKEN_ACCEPTED,
            TOKEN_NOT_VALID=TOKEN_NOT_VALID,
            PROTOCOL_ERROR=PROTOCOL_ERROR,
            ACCEPTED=PREPARING_TO_CHARGE,
            CANCELED_RESERVATION=_make_texts(_("The reservation has been cancelled")),
            EVSE_INOPERATIVE=_make_texts(_("The charger is inoperative")),
            FAILED=_make_texts(_("Failed to start the charging")),
            NOT_SUPPORTED=_make_texts(
                _("The operation is not supported by the charger")
            ),
            REJECTED=_make_texts(_("The command was rejected by the charger")),
            TIMEOUT=_make_texts(_("The charger is inoperative")),
            UNKNOWN_RESERVATION=_make_texts(
                _("There has been a problem with the reservation")
            ),
        )
        return _texts.get(s, default)


class UserMessages:
    approve_charging = dict(
        en='Please approve charging at "{location}". '
        'Prices: {price}. Respond "Ok" or click below to start charging, '
        '"cancel" to decline or "report" if you suspect fraud. '
        "To approve and see real-time charging status, go to {url}.",
        bg='Моля, одобрете таксуването на "{location}". '
        'Цени: {price}. Отговорете "Ok" или щракнете по-долу, за да започнете зареждането, '
        '"отменете", за да откажете или "докладете", ако подозирате измама. '
        "За да одобрите и видите състоянието на таксуване в реално време, отидете на {url}.",
        fi='Ole hyvä ja vahvista lataus latauspisteessä "{location}". '
        'Hinta: {price}. Vastaa "Ok" tai klikkaa linkkiä, '
        '"ei" kieltääksesi tai "raportoi", jos epäilet väärinkäytöstä. '
        "Näet reaaliaikaisen tilanteen osoitteessa {url}.",
    )


def get_language(language: str, source: Optional[list]) -> str:
    """
    >>> get_language('en', [dict(language='EN', text='The token is accepted')])
    'The token is accepted'
    >>> get_language('xy', [dict(language='EN', text='The token is accepted')])
    'The token is accepted'
    >>> get_language('xy', None)
    ''
    """
    language = language.upper() or "en"
    if not source or not language:
        return ""
    if isinstance(source, str):
        return source
    result = [
        item.get("text") for item in source if item.get("language").upper() == language
    ]
    if len(result):
        return result[0]
    else:
        return get_language("en", source) if language.lower() != "en" else ""


class AuthorizationEnum(models.TextChoices):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    NO_CREDIT = "NO_CREDIT"
    NOT_ALLOWED = "NOT_ALLOWED"

    def __eq__(self, other):
        if isinstance(other, AuthorizationEnum):
            return self.value == other.value
        elif isinstance(other, str):
            return self.value == other
        else:
            return False

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value

    def __hash__(self):
        return hash(self.value)


DAY_OF_WEEK_CHOICES = (
    ("MONDAY", _("Monday")),
    ("TUESDAY", _("Tuesday")),
    ("WEDNESDAY", _("Wednesday")),
    ("THURSDAY", _("Thursday")),
    ("FRIDAY", _("Friday")),
    ("SATURDAY", _("Saturday")),
    ("SUNDAY", _("Sunday")),
)

# dict(MONDAY=0, TUESDAY=1,...)
DAY_OF_WEEK_NUMBERS = dict(
    [(DAY_OF_WEEK_CHOICES[x][0], x) for x in range(0, len(DAY_OF_WEEK_CHOICES))]
)

RESERVATION_CHOICES = (
    ("RESERVATION", _("Costs for a reservation")),
    ("RESERVATION_EXPIRES", _("Costs for a reservation that expires")),
)


class OCPIFacility(models.TextChoices):
    HOTEL = "HOTEL", _lazy("Hotel")
    RESTAURANT = "RESTAURANT", _lazy("Restaurant")
    CAFE = "CAFE", _lazy("Cafe")
    MALL = "MALL", _lazy("Mall")
    SUPERMARKET = "SUPERMARKET", _lazy("Supermarket")
    PARK = "PARK", _lazy("Park")
    CINEMA = "CINEMA", _lazy("Cinema")
    THEATER = "THEATER", _lazy("Theater")
    STADIUM = "STADIUM", _lazy("Stadium")
    CONFERENCE_CENTER = "CONFERENCE_CENTER", _lazy("Conference Center")
    WORKPLACE = "WORKPLACE", _lazy("Workplace")
    AIRPORT = "AIRPORT", _lazy("Airport")
    TRAIN_STATION = "TRAIN_STATION", _lazy("Train Station")
    METRO_STATION = "METRO_STATION", _lazy("Metro Station")
    BUS_STATION = "BUS_STATION", _lazy("Bus Station")
    TAXI_STAND = "TAXI_STAND", _lazy("Taxi Stand")
    GAS_STATION = "GAS_STATION", _lazy("Gas Station")
    PARKING_LOT = "PARKING_LOT", _lazy("Parking Lot")
    CHARGING_STATION = "CHARGING_STATION", _lazy("Charging Station")
    RESIDENTIAL_AREA = "RESIDENTIAL_AREA", _lazy("Residential Area")
    INDUSTRIAL_AREA = "INDUSTRIAL_AREA", _lazy("Industrial Area")
    HOSPITAL = "HOSPITAL", _lazy("Hospital")
    UNIVERSITY = "UNIVERSITY", _lazy("University")
    SCHOOL = "SCHOOL", _lazy("School")
    LIBRARY = "LIBRARY", _lazy("Library")
    OTHER = "OTHER", _lazy("Other")


class OCPICapability(models.TextChoices):
    CHARGING_PROFILE_CAPABLE = "CHARGING_PROFILE_CAPABLE", _lazy("Charging profiles")
    CHARGING_PREFERENCES_CAPABLE = (
        "CHARGING_PREFERENCES_CAPABLE",
        _lazy("Charging preferences"),
    )
    CHIP_CARD_SUPPORT = "CHIP_CARD_SUPPORT", _lazy("Chip cards")
    CONTACTLESS_CARD_SUPPORT = "CONTACTLESS_CARD_SUPPORT", _lazy("Contactless cards")
    PED_TERMINAL = "PED_TERMINAL", _lazy("Payment terminal with a PIN-pad")
    REMOTE_START_STOP_CAPABLE = "REMOTE_START_STOP_CAPABLE", _lazy("Remote start/stop")
    RESERVABLE = "RESERVABLE", _lazy("Reservation")
    RFID_READER = "RFID_READER", _lazy("RFID token reader")
    CREDIT_CARD_PAYABLE = "CREDIT_CARD_PAYABLE", _lazy("Credit cards")
    DEBIT_CARD_PAYABLE = "DEBIT_CARD_PAYABLE", _lazy("Debit cards")
    START_SESSION_CONNECTOR_REQUIRED = (
        "START_SESSION_CONNECTOR_REQUIRED",
        _lazy("Connector required in StartSession"),
    )
    TOKEN_GROUP_CAPABLE = "TOKEN_GROUP_CAPABLE", _lazy("Token groups")
    UNLOCK_CAPABLE = "UNLOCK_CAPABLE", _lazy("Remote connector unlock")


LANGUAGES_ISO_2 = {
    iso2[:2].upper() for iso2, iso3 in langcodes.data_dicts.LANGUAGE_ALPHA3.items()
}
LANGUAGE_CHOICES = [
    (iso2.lower(), _(langcodes.Language.get(iso2).display_name("en")))
    for iso2 in LANGUAGES_ISO_2
]
LANGUAGE_CHOICES.sort(key=lambda x: x[1])

TIMEZONE_CHOICES = [(tz, tz) for tz in pytz.all_timezones]

DYNAMIC_PRICE_SOURCE_CHOICES = (
    ("BGDA", "Bulgaria day ahead"),
    ("BGID", "Bulgaria intraday"),
    ("IBEXBGIDM", "IBEX.bg Intraday"),
    ("IBEXBGDAM", "IBEX.bg Day ahead"),
    ("NPFI", "Nordpool Finland"),
    ("NPEE", "Nordpool Estonia"),
    ("NPLV", "Nordpool Latvia"),
    ("NPLT", "Nordpool Lithuania"),
    ("NPOslo", "Nordpool Oslo"),
    ("NPBergen", "Nordpool Bergen"),
    ("NPMolde", "Nordpool Molde"),
    ("NPSE1", "Nordpool Sweden 1"),
    ("NPSE2", "Nordpool Sweden 2"),
    ("NPSE3", "Nordpool Sweden 3"),
    ("NPSE4", "Nordpool Sweden 4"),
    ("NPDK1", "Nordpool Denmark 1"),
    ("NPDK2", "Nordpool Denmark 2"),
    ("NPAT", "Nordpool Austria"),
    ("NPBE", "Nordpool Belgium"),
    ("NPFR", "Nordpool France"),
    ("NPNL", "Nordpool Netherlands"),
)

PARKING_CHOICES = (
    ("ALONG_MOTORWAY", "Along a motorway"),
    ("PARKING_GARAGE", "Parking garage"),
    ("PARKING_LOT", "Parking lot"),
    ("ON_DRIVEWAY", "Driveway"),
    ("ON_STREET", "Street"),
    ("UNDERGROUND_GARAGE", "Underground garage"),
)


class ParkingChoices(Enum):
    ALONG_MOTORWAY = "ALONG_MOTORWAY"
    PARKING_GARAGE = "PARKING_GARAGE"
    PARKING_LOT = "PARKING_LOT"
    ON_DRIVEWAY = "ON_DRIVEWAY"
    ON_STREET = "ON_STREET"
    UNDERGROUND_GARAGE = "UNDERGROUND_GARAGE"


AVAILABLE = "AVAILABLE"
BLOCKED = "BLOCKED"
CHARGING = "CHARGING"
INOPERATIVE = "INOPERATIVE"
OUTOFORDER = "OUTOFORDER"
PLANNED = "PLANNED"
REMOVED = "REMOVED"
RESERVED = "RESERVED"
UNKNOWN = "UNKNOWN"

EVSE_STATUS_CHOICES = (
    (AVAILABLE, _("Available")),
    (BLOCKED, _("Physically blocked")),
    (CHARGING, _("Charging")),
    (INOPERATIVE, _("Inoperative")),
    (OUTOFORDER, _("Out of order")),
    (PLANNED, _("Planned, will be operating soon")),
    (REMOVED, _("Discontinued/removed")),
    (RESERVED, _("Reserved for a particular EV driver")),
    (UNKNOWN, _("No status information available (also used when offline)")),
)


class EVSEStatus(Enum):
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    CHARGING = "CHARGING"
    INOPERATIVE = "INOPERATIVE"
    OUTOFORDER = "OUTOFORDER"
    PLANNED = "PLANNED"
    REMOVED = "REMOVED"
    RESERVED = "RESERVED"
    UNKNOWN = "UNKNOWN"


class ParkingRestriction(Enum):
    EV_ONLY = "EV_ONLY"
    PLUGGED = "PLUGGED"
    DISABLED = "DISABLED"
    CUSTOMERS = "CUSTOMERS"
    MOTORCYCLES = "MOTORCYCLES"


class EnvironmentalImpactCategory(Enum):
    NUCLEAR_WASTE = "NUCLEAR_WASTE"
    CARBON_DIOXIDE = "CARBON_DIOXIDE"


class EnergySourceCategory(Enum):
    NUCLEAR = "NUCLEAR"
    GENERAL_FOSSIL = "GENERAL_FOSSIL"
    COAL = "COAL"
    GAS = "GAS"
    GENERAL_GREEN = "GENERAL_GREEN"
    SOLAR = "SOLAR"
    WIND = "WIND"
    WATER = "WATER"


class RoamingProtocol(Enum):
    OCPI = "Open Charge Point Interface"
    OICP = "Open InterCharge Protocol"


ROAMING_PROTOCOL_CHOICES = [
    (protocol.name, protocol.value) for protocol in RoamingProtocol
]
