from enum import Enum

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
    (OcpiModuleEnum.CREDENTIALS.name, 'Credentials'),
    (OcpiModuleEnum.LOCATIONS.name, 'Locations'),
    (OcpiModuleEnum.TOKENS.name, 'Tokens'),
    (OcpiModuleEnum.COMMANDS.name, 'Commands'),
    (OcpiModuleEnum.TARIFFS.name, 'Tariffs'),
    (OcpiModuleEnum.CDRS.name, 'Charge Detail Records'),
    (OcpiModuleEnum.SESSIONS.name, 'Sessions'),
    (OcpiModuleEnum.HUBCLIENTINFO.name, 'Hubclientinfo'),
)

ROLE_OPTIONS = ('CPO', 'EMSP', 'HUB', 'NSP', 'NAP', 'SCSP')


class EndpointRoleEnum(Enum):
    SENDER = 'SENDER'
    RECEIVER = 'RECEIVER'


ENDPOINT_ROLE_CHOICES = (
    (EndpointRoleEnum.SENDER.value, 'Sender'),
    (EndpointRoleEnum.RECEIVER.value, 'Receiver')
)
