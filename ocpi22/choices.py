from enum import Enum

import cachetools
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext_noop as _


class OcpiRolesEnum(Enum):
    CPO = 'CPO'
    EMSP = 'EMSP'
    HUB = 'HUB'
    NAP = 'NAP'
    NSP = 'NSP'
    OTHER = 'OTHER'
    SCSP = 'SCSP'


ROLE_CHOICES = (
    ('CPO', 'Charge Point operator'),
    ('EMSP', 'Emobility Service Provider'),
    ('HUB', 'Hub'),
    ('NAP', 'National Access Point'),
    ('NSP', 'Navigation Service Provider'),
    ('OTHER', 'Other'),
    ('SCSP', 'Smart Charging Service Provider'),
)

CONNECTED = 'CONNECTED'
OFFLINE = 'OFFLINE'
PLANNED = 'PLANNED'
SUSPENDED = 'SUSPENDED'

CONNECTION_STATUS_CHOICES = [
    (x, x.capitalize()) for x in (CONNECTED, OFFLINE, PLANNED, SUSPENDED)
]


class OcpiModuleEnum(Enum):
    CREDENTIALS = 'credentials'
    LOCATIONS = 'locations'
    TOKENS = 'tokens'
    COMMANDS = 'commands'
    TARIFFS = 'tariffs'
    CDRS = 'cdrs'
    SESSIONS = 'sessions'
    HUBCLIENTINFO = 'hubclientinfo'


IDENTIFIER_CHOICES = (
    (OcpiModuleEnum.CREDENTIALS.value, 'Credentials'),
    (OcpiModuleEnum.LOCATIONS.value, 'Locations'),
    (OcpiModuleEnum.TOKENS.value, 'Tokens'),
    (OcpiModuleEnum.COMMANDS.value, 'Commands'),
    (OcpiModuleEnum.TARIFFS.value, 'Tariffs'),
    (OcpiModuleEnum.CDRS.value, 'Charge Detail Records'),
    (OcpiModuleEnum.SESSIONS.value, 'Sessions'),
    (OcpiModuleEnum.HUBCLIENTINFO.value, 'Hubclientinfo'),
)

ROLE_OPTIONS = ('CPO', 'EMSP', 'HUB', 'NSP', 'NAP', 'SCSP')


class EndpointRoleEnum(Enum):
    SENDER = 'SENDER'
    RECEIVER = 'RECEIVER'


ENDPOINT_ROLE_CHOICES = (
    (EndpointRoleEnum.SENDER.value, 'Sender'),
    (EndpointRoleEnum.RECEIVER.value, 'Receiver')
)


class OcppStatusEnum(Enum):
    AVAILABLE = 'AVAILABLE'
    PREPARING = 'PREPARING'
    CHARGING = 'CHARGING'
    SUSPENDEDEV = 'SUSPENDEDEV'
    SUSPENDEDEVSE = 'SUSPENDEDEVSE'
    FINISHING = 'FINISHING'
    RESERVED = 'RESERVED'
    UNAVAILABLE = 'UNAVAILABLE'
    FAULTED = 'FAULTED'


OCPP_STATUS_CHOICES = [
    (e.value, e.value.capitalize())
    for e in OcppStatusEnum
]


class CdrDimensionEnum(Enum):
    # Average charging current during this ChargingPeriod: defined in A (Ampere).
    # When negative, the current is flowing from the EV to the grid.
    CURRENT = 'CURRENT'

    # Total amount of energy (dis-)charged during this ChargingPeriod: defined in kWh.
    # When negative, more energy was feed into the grid then charged into the EV. Default step_size is 1.
    ENERGY = 'ENERGY'

    # Total amount of energy feed back into the grid: defined in kWh.
    ENERGY_EXPORT = 'ENERGY_EXPORT'

    # Total amount of energy charged, defined in kWh.
    ENERGY_IMPORT = 'ENERGY_IMPORT'

    # Sum of the maximum current over all phases, reached during this ChargingPeriod: defined in A (Ampere).
    MAX_CURRENT = 'MAX_CURRENT'

    # Sum of the minimum current over all phases, reached during this ChargingPeriod,
    # when negative, current has flowed from the EV to the grid. Defined in A (Ampere).
    MIN_CURRENT = 'MIN_CURRENT'

    # Maximum power reached during this ChargingPeriod: defined in kW (Kilowatt).
    MAX_POWER = 'MAX_POWER'

    # Minimum power reached during this ChargingPeriod: defined in kW (Kilowatt),
    # when negative, the power has flowed from the EV to the grid.
    MIN_POWER = 'MIN_POWER'

    # Time during this ChargingPeriod not charging: defined in hours, default step_size multiplier is 1 second.
    PARKING_TIME = 'PARKING_TIME'

    # Average power during this ChargingPeriod: defined in kW (Kilowatt).
    # When negative,the power is flowing from the EV to the grid.
    POWER = 'POWER'

    # Time during this ChargingPeriod Charge Point has been reserved and not yet been in use for this customer:
    # defined in hours, default step_size multiplier is 1 second.
    RESERVATION_TIME = 'RESERVATION_TIME'

    # Current state of charge of the EV, in percentage, values allowed: 0 to 100. See note below.
    STATE_OF_CHARGE = 'STATE_OF_CHARGE'

    # Time charging during this ChargingPeriod: defined in hours, default step_size multiplier is 1 second.
    TIME = 'TIME'


CDR_DIMENSION_CHOICES = [
    (e.value, e.value.capitalize().replace('_', ' '))
    for e in CdrDimensionEnum
]


@cachetools.cached(cache={})
def _make_texts(english_text):
    result = []
    for language, _name in settings.LANGUAGES:
        with translation.override(language):
            if language == 'en':
                tr = english_text
            else:
                tr = translation.gettext(english_text)
                if tr == english_text:
                    # No translation available
                    continue
            result.append(
                dict(
                    language=language.upper(),
                    text=tr
                )
            )
    return result


class MessageTexts:
    @classmethod
    def get(cls, s, default=None):
        PREPARING_TO_CHARGE = _make_texts(_('Preparing to charge'))
        STOPPING_TO_CHARGE = _make_texts(_('Stopping charging session'))
        # dict(language='FI', text='Latausta viimeistellään'),
        EVSE_OCCUPIED = _make_texts(_('The charger is currently in use'))
        # dict(language='FI', text='Latauspiste on parhaillaan käytössä'),
        DEFAULT_CHARGER_ERROR_TEXT = _make_texts(_('Unable to start charging at this time'))
        # dict(language='FI', text='Lataus ei ole mahdollista tällä hetkellä'),
        MS_CONNECTION_ERROR = _make_texts(_('Unable to connect to charge point management system'))
        # dict(language='FI', text='Yhteys latauspisteen hallintajärjestelmään on poikki'),
        NO_BALANCE = _make_texts(_("The token doesn't have enough balance on the account"))
        # dict(language='FI', text='Lataustilillä ei ole riittävästi katetta'),
        TOKEN_ACCEPTED = _make_texts(_('The token is accepted'))
        # dict(language='FI', text='Lataustunniste on hyväksytty'),
        TOKEN_NOT_VALID = _make_texts(_('Your token is no longer valid'))
        # dict(language='FI', text='Lataustunniste ei ole enää voimassa'),

        _texts = dict(
            START_ACCEPTED=PREPARING_TO_CHARGE,
            STOPPING_TO_CHARGE=STOPPING_TO_CHARGE,
            EVSE_OCCUPIED=EVSE_OCCUPIED,
            STOP_ACCEPTED=STOPPING_TO_CHARGE,
            DEFAULT_CHARGER_ERROR_TEXT=DEFAULT_CHARGER_ERROR_TEXT,
            MS_CONNECTION_ERROR=MS_CONNECTION_ERROR,
            NO_BALANCE=NO_BALANCE,
            TOKEN_ACCEPTED=TOKEN_ACCEPTED,
            TOKEN_NOT_VALID=TOKEN_NOT_VALID,
            ACCEPTED=PREPARING_TO_CHARGE,
            CANCELED_RESERVATION=_make_texts(_('The reservation has been cancelled')),
            EVSE_INOPERATIVE=_make_texts(_('The charger is inoperative')),
            FAILED=_make_texts(_('Failed to start the charging')),
            NOT_SUPPORTED=_make_texts(_('The operation is not supported by the charger')),
            REJECTED=_make_texts(_('The command was rejected by the charger')),
            TIMEOUT=_make_texts(_("The charger is inoperative")),
            UNKNOWN_RESERVATION=_make_texts(_('There has been a problem with the reservation')),
        )
        return _texts.get(s, default)


class UserMessages:
    approve_charging = dict(
        en='Please approve charging at "{location}". '
           'Prices: {price}. Respond "Ok" or click below to start charging, '
           '"cancel" to decline or "report" if you suspect fraud. '
           'To approve and see real-time charging status, go to {url}.',
        bg='Моля, одобрете таксуването на "{location}". '
           'Цени: {price}. Отговорете "Ok" или щракнете по-долу, за да започнете зареждането, '
           '"отменете", за да откажете или "докладете", ако подозирате измама. '
           'За да одобрите и видите състоянието на таксуване в реално време, отидете на {url}.',
        fi='Ole hyvä ja vahvista lataus latauspisteessä "{location}". '
           'Hinta: {price}. Vastaa "Ok" tai klikkaa linkkiä, '
           '"ei" kieltääksesi tai "raportoi", jos epäilet väärinkäytöstä. '
           'Näet reaaliaikaisen tilanteen osoitteessa {url}.',
    )


def get_language(language: str, source: list) -> str:
    """
    >>> get_language('en', [dict(language='en', text='The token is accepted')])
    'The token is accepted'
    >>> get_language('xy', [dict(language='en', text='The token is accepted')])
    ''
    >>> get_language('xy', None)
    ''
    """
    language = language.upper()
    if not source or not language:
        return ''
    result = [l.get('text') for l in source if l.get('language').upper() == language]
    if len(result):
        return result[0]
    else:
        return ''
