from enum import Enum


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


class MessageTexts:
    PREPARING_TO_CHARGE = [
        dict(language='EN', text='Preparing to charge'),
        dict(language='BG', text='Подготовка за зареждане'),
        dict(language='FI', text='Latausta valmistellaan'),
    ]
    EVSE_OCCUPIED = [
        dict(language='EN', text='The charger is currently in use'),
        dict(language='BG', text=''),
        dict(language='FI', text='Latauspiste on parhaillaan käytössä'),
    ]
    DEFAULT_CHARGER_ERROR_TEXT = [
        dict(language='EN', text='Unable to start charging at this time'),
        dict(language='BG', text=''),
        dict(language='FI', text='Lataus ei ole mahdollista tällä hetkellä'),
    ]
    MS_CONNECTION_ERROR = [
        dict(language='EN', text='Unable to connect to charge point management system'),
        dict(language='BG', text='Не може да се свърже със системата '
                                 'за управление на точките на зареждане'),
        dict(language='FI', text='Yhteys latauspisteen hallintajärjestelmään on poikki'),
    ]
    _texts = dict(
        ACCEPTED=PREPARING_TO_CHARGE,
        EVSE_OCCUPIED=EVSE_OCCUPIED,
    )

    @classmethod
    def get(cls, s, default=None):
        return cls._texts.get(s, default)
