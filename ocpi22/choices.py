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
