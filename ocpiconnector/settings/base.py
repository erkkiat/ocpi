# Django settings for ocpiconnector project.
import os
from datetime import timedelta
from distutils.util import strtobool

from corsheaders.defaults import default_headers
from django.conf.locale.en import formats as locale_formats
from django.utils.translation import gettext_lazy as _

from ocpiconnector.settings.configure_sentry import setup_sentry
from ocpiconnector.settings.infra_services import CustomJsonFormatter

setup_sentry()

TRUE_OPTIONS = (1, "1", True, "True", "true")


def env_bool(key, default=False) -> bool:
    return bool(os.environ.get(key, default) in TRUE_OPTIONS)


DEBUG = env_bool("DEBUG", False)

RENDER_ONLY_JSON = env_bool("RENDER_ONLY_JSON", False)

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["https_proxy"] = FIXIE_URL
os.environ["http_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"

DATETIME_FORMAT = os.environ.get("DATETIME_FORMAT", "%d.%m.%Y %H:%M")
DATE_FORMAT = os.environ.get("DATE_FORMAT", "%d.%m.%Y")
locale_formats.DATETIME_FORMAT = os.environ.get("DATETIME_FORMAT_LOCALE", "D j.n.Y H:i")
DECIMAL_SEPARATOR = os.environ.get("DECIMAL_SEPARATOR", ",")
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "EUR")

CPO_API = env_bool("CPO_API", False)
MSP_API = env_bool("MSP_API", False)

PERFORMANCE_TEST = env_bool("PERFORMANCE_TEST", False)
CPO_SIMULATOR = env_bool("CPO_SIMULATOR", False)

ALLOW_ADMIN_DELETE_AND_CHANGE = env_bool("ALLOW_ADMIN_DELETE_AND_CHANGE", False)

APPEND_SLASH = False  # Accept requests with no trailing slash
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # Allow more than 1000 fields in POST requests
TEMPLATE_DEBUG = DEBUG
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = os.environ.get("SECRET_KEY")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT")

# Find a Redis, since Heroku Redis services use different environment variables
REDIS_KEYS = ["STACKHERO_REDIS_URL_TLS", "REDIS_URL", "REDISCLOUD_URL"]
REDIS_URLS = [os.environ.get(key, None) for key in REDIS_KEYS]
REDIS_URL = next((url for url in REDIS_URLS if url), None)
REDIS_SESSION_CACHE_NAMESPACE = "sessioncache"

# Send updates to partners who we have Credentials for
SEND_UPDATES = env_bool("SEND_UPDATES", True)
SERVE_STATIC_FILES = env_bool("SERVE_STATIC_FILES", True)
MAX_NUMBER_OF_PARTNERS = os.environ.get("MAX_NUMBER_OF_PARTNERS", 1000)

REMOTE_COMMAND_EXPIRATION = os.environ.get("REMOTE_COMMAND_EXPIRATION", 2 * 60)
MAXIMUM_CHARGE_SESSION_LENGTH_IN_SECONDS = os.environ.get(
    "MAXIMUM_CHARGE_SESSION_LENGTH_IN_SECONDS", 2 * 24 * 60 * 60
)

# Use the builtin account functionality and require a wallet balance when user wants to charge
USE_ACCOUNTS = env_bool("USE_ACCOUNTS", False)
REQUIRE_WALLET_BALANCE = bool(env_bool("REQUIRE_WALLET_BALANCE", True) and USE_ACCOUNTS)

OCPI_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
OICP_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
OCPI_22_URL = "/ocpi/2.2/"
OCPI_221_URL = "/ocpi/2.2.1/"
VERSION_URLS = {OCPI_22_URL, OCPI_221_URL}
VERSIONS = {"2.2", "2.2.1"}

# How often to check that other party is alive
STILL_ALIVE_FREQUENCY = os.environ.get("STILL_ALIVE_FREQUENCY", 60 * 5)

# How long can a charger be reserved
MAXIMUM_RESERVATION = os.environ.get("MAXIMUM_RESERVATION", 60 * 30)

# Send updates asynchronously using Celery
BACKGROUND_SEND = env_bool("BACKGROUND_SEND", True)

ADMINS = [("Erkki Tapola", "erkki.tapola@solidroam.com")]
MANAGERS = ADMINS

TIMEOUT_FOR_COMMANDS = 2 * 60

HOSTNAME = os.environ["HOSTNAME"]
HOSTNAME_SHORT = HOSTNAME.split(".")[0]
SCHEME = os.environ.get("SCHEME", "https")

OCPI_SPECIFICATION_URL = "https://github.com/ocpi/ocpi/blob/release-2.2-bugfixes/"

# These are in the OCPI 2.2 specification, so don't change them
OCPI_22_MAX_ADDRESS_LENGTH = 45
OCPI_22_MAX_TIME_ZONE_LENGTH = 64
OCPI_22_MAX_UID_LENGTH = 36

HOTLINE = os.environ.get("HOTLINE", "+3256380211")


def parse_jawsdb_maria_url(url):
    protocol, url = url.split("://")
    assert (
        protocol == "mysql" and '"' not in protocol and "'" not in protocol
    ), "Only mysql:// is supported, check that you don't have quotes in the JAWSDB_MARIA_URL"
    credentials, connection = url.split("@")
    userid, password = credentials.split(":")
    connection, database = connection.split("/")
    host, port = connection.split(":")
    return dict(
        default={
            "ENGINE": "django.db.backends.mysql",
            "NAME": database,
            "USER": userid,
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
            "OPTIONS": {
                "sql_mode": "traditional",
                "init_command": "SET GLOBAL max_connections = 100000",  # Activate for performance testing if needed
            },
            # 'CONN_MAX_AGE': 15,
        }
    )


# JAWSDB_MARIA_URL = os.environ.get('JAWSDB_MARIA_URL',
#                                   os.environ.get('JAWSDB_URL', None))
# if JAWSDB_MARIA_URL:
#     # We're running on Heroku
#     DATABASES = parse_jawsdb_maria_url(JAWSDB_MARIA_URL)
# else:

# if ':' in HOSTNAME:
#     HOST, PORT = HOSTNAME.split(':')

DATABASE_URL = os.environ.get("DATABASE_URL", os.environ.get("JAWSDB_URL", ""))

assert DATABASE_URL, "Please provide either a mysql or a postgres database URL"

# GDPR_LOG_DATABASE_NAME = 'default'
# DATABASE_ROUTERS = ['gdpr_assist.routers.EventLogRouter']
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts
def hostname_variants(hostname):
    """
    >>> hostname_variants('testi10-ocpi.herokuapp.com')
    ['testi10-ocpi.herokuapp.com', 'testi10-ocpi.ocpiconnector.com', 'testi10-ocpi.roamingconnector.com', 'testi10-ocpi.ocpiguide.com', 'testi10-ocpi.chargerhub.eu', 'testi10-ocpi.solidroam.com']
    >>> hostname_variants('cpo-ocpi.ocpiconnector.com')
    ['cpo-ocpi.herokuapp.com', 'cpo-ocpi.ocpiconnector.com', 'cpo-ocpi.roamingconnector.com', 'cpo-ocpi.ocpiguide.com', 'cpo-ocpi.chargerhub.eu', 'cpo-ocpi.solidroam.com']
    >>> hostname_variants('cpo')
    ['cpo.herokuapp.com', 'cpo.ocpiconnector.com', 'cpo.roamingconnector.com', 'cpo.ocpiguide.com', 'cpo.chargerhub.eu', 'cpo.solidroam.com']
    """
    components = hostname.split(".")
    return [
        f"{components[0]}.{x}"
        for x in [
            "herokuapp.com",
            "ocpiconnector.com",
            "roamingconnector.com",
            "ocpiguide.com",
            "chargerhub.eu",
            "solidroam.com",
        ]
    ]


HUBJECT_HOSTS = []

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "testserver.test",
] + hostname_variants(HOSTNAME)

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = os.environ.get("LANGUAGE_CODE", "en")

LANGUAGES = [
    ("en", _("English")),
    ("nl", _("Dutch, Flemish")),
    ("fr", _("French")),
    ("de", _("German")),
    ("es", _("Spanish")),
    ("it", _("Italian")),
    ("pt", _("Portuguese")),
    ("lb", _("Luxembourgish")),
    ("cy", _("Welsh")),
    ("ga", _("Irish")),
    ("be", _("Belarusian")),
    ("bg", _("Bulgarian")),
    ("ro", _("Romanian")),
    ("bs", _("Bosnian")),
    ("mk", _("Macedonian")),
    ("sq", _("Albanian")),
    ("sr", _("Serbian")),
    ("tr", _("Turkish")),
    ("uk", _("Ukrainian")),
    ("el", _("Greek")),
    ("pl", _("Polish")),
    ("hu", _("Hungarian")),
    ("cs", _("Czech")),
    ("sk", _("Slovak")),
    ("sl", _("Slovenian")),
    ("fi", _("Finnish")),
    ("nn", _("Nynorsk")),
    ("da", _("Danish")),
    ("sv", _("Swedish")),
    ("is", _("Icelandic")),
    ("et", _("Estonian")),
    ("lt", _("Lithuanian")),
    ("lv", _("Latvian")),
    ("af", _("Afrikans")),
    # ('mi', _('Maori')),
]

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True
TIME_ZONE = os.environ.get("TIMEZONE", "UTC")

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = ""

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = ""

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
STATIC_URL = os.environ.get("EDGE_URL", "") + "/static/"

if os.environ.get("LOCAL_STATIC") and False:
    STATIC_ROOT = os.path.join(BASE_DIR, "ocpiconnector/../static")
else:
    STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"

# Additional locations of static files
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    # 'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
    #     'django.template.loaders.eggs.Loader',
)

MIDDLEWARE = [
    "middlewares.AllowHealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "ocpi22.middleware.ErrorLoggingMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # Make sure this stays above OCPIHubMiddleware
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "ocpi22.middleware.OCPI221HeadersMiddleware",
    "ocpiconnector.logging_middleware.LoggingMiddleware",
    "axes.middleware.AxesMiddleware",
]

if "MOESIF_APPLICATION_ID" in os.environ:
    MIDDLEWARE.append("moesifdjango.middleware.moesif_middleware")

if os.environ.get("DEBUG_MIDDLEWARE") in TRUE_OPTIONS:
    MIDDLEWARE.append("ocpi22.middleware.DebugMiddleware")

if os.environ.get("HUB"):
    # Running as a hub, start acting like one
    MIDDLEWARE.append("ocpi22.middleware.OCPIHubMiddleware")

ROOT_URLCONF = "ocpiconnector.urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "ocpi22",
    "ocpiconnector",
    "webhooks",
    "settlement",
    "django.contrib.admin",
    "whitenoise",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "nested_admin",
    "gdpr_assist",
    "corsheaders",
    "payment",
    "drf_yasg",
    "ninja_jwt",
    "ninja_extra",
    "axes",
]

CORS_ORIGIN_ALLOW_ALL = env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOW_HEADERS = (
    *default_headers,
    "access-control-allow-origin",
)

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = "ocpiconnector.wsgi.application"
ASGI_APPLICATION = "ocpiconnector.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "ocpi22.context_processors.export_environment_variables",
                "ocpi22.context_processors.export_issue_count",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

# Todo: Use Redis as Messages backend

MESSAGE_STORAGE = "ocpiconnector.util.SessionDedupStorage"  # Removes duplicate messages, like the OCPI 2.2 explanations
SESSION_SERIALIZER = "django.contrib.sessions.serializers.JSONSerializer"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": CustomJsonFormatter,
            "format": "%(asctime)s %(levelname)s %(name)s %(funcName)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "level": "INFO",
        },
        "sentry": {
            "class": "sentry_sdk.integrations.logging.EventHandler",
            "level": "ERROR",
        },
    },
    "root": {
        "handlers": ["console", "sentry"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "level": "INFO",
            "propagate": True,
        },
        "django.request": {
            "level": "INFO",
            "propagate": True,
        },
        "django.db.backends": {
            "level": "WARNING",
            "propagate": True,
        },
        "django.core.management": {
            "level": "INFO",
            "propagate": True,
        },
        "gunicorn.error": {
            "level": "INFO",
            "propagate": True,
        },
        "ocpi22.cpo.mqtt.mqtt_subscriber": {
            "level": "INFO",
            "propagate": True,
        },
    },
}


# OAuth2
LOGIN_URL = "/admin/login/"

OAUTH2_PROVIDER = {
    # this is the list of available scopes
    "SCOPES": {
        "read": "Read scope",
        "write": "Write scope",
        "groups": "Access to your groups",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "rest_framework.schemas.coreapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": ["ocpi22.ocpi.auth.OCPIPermission"],
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ),
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_METADATA_CLASS": "ocpi22.util.MyMetadata",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

if not RENDER_ONLY_JSON:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )

# Celery Configuration Options
# CELERY_TIMEZONE = "Finland/Helsinki"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TASK_DEFAULT_QUEUE = os.environ.get("CELERY_QUEUE_NAME", "celery-django-mid")
CELERY_TASK_ALWAYS_EAGER = strtobool(os.getenv("CELERY_TASK_ALWAYS_EAGER", "False"))
CELERY_TASK_IGNORE_RESULTS = True
CELERY_TASK_PUBLISH_RETRY = True
CELERY_TASK_PUBLISH_RETRY_POLICY = {
    "max_retries": 5,
    "interval_start": 0,
    "interval_step": 1,
    "interval_max": 5,
}

CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = None

BROKER_TRANSPORT_OPTIONS = {
    "socket_timeout": 30,
    "socket_connect_timeout": 30,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "health_check_interval": 30,
    "max_connections": 50,
}

CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {
    "socket_timeout": 30,
    "socket_connect_timeout": 30,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "health_check_interval": 30,
    "max_connections": 20,
}

CELERY_BROKER_POOL_LIMIT = 20
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000

# JWT authentication
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=48)
    if PERFORMANCE_TEST
    else timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7)
    if PERFORMANCE_TEST
    else timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": "SolidRoam",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}


def identify_user(req, res):
    # For Moesif API analytics
    if req.user and req.user.is_authenticated:
        return req.user.username
    else:
        return None


MOESIF_MIDDLEWARE = {
    "APPLICATION_ID": os.environ.get("MOESIF_APPLICATION_ID"),
    "CAPTURE_OUTGOING_REQUESTS": True,  # Set to True to also capture outgoing calls to 3rd parties.
    "IDENTIFY_USER": identify_user,  # Optional hook to link API calls to users
}

CRISPY_TEMPLATE_PACK = "bootstrap4"

HUBJECT_URL = os.environ.get("HUBJECT_URL", "https://service.hubject.com/api/oicp/")
HUBJECT_CLIENT_CERTIFICATE = os.environ.get("HUBJECT_CLIENT_CERTIFICATE")
HUBJECT_PRIVATE_KEY = os.environ.get("HUBJECT_PRIVATE_KEY")
HUBJECT_CA_CERTIFICATE = os.environ.get("HUBJECT_CA_CERTIFICATE")
HUBJECT_OPERATOR_ID = os.environ.get("HUBJECT_OPERATOR_ID", "DE*ICE")
HUB_ID_MAX_LENGTH = 36
ENABLE_HUBJECT = env_bool("ENABLE_HUBJECT", False)
HUBJECT_TIMEOUT_SECONDS = os.environ.get("HUBJECT_TIMEOUT_SECONDS", 10)
HUBJECT_EMP_ID = os.getenv("HUBJECT_EMP_ID")

FIXIE_URL = os.environ.get("FIXIE_URL", "")

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")
SMAPPEE_METER_VALUES_TOPIC = os.getenv("SMAPPEE_METER_VALUES_TOPIC")

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = os.getenv("MQTT_PORT", 1883)

DEFAULT_OICP_PRICE = os.environ.get("DEFAULT_OICP_PRICE")
DEFAULT_OICP_CURRENCY = os.environ.get("DEFAULT_OICP_CURRENCY")
DEFAULT_OICP_PRICE_REFERENCE = os.environ.get("DEFAULT_OICP_PRICE_REFERENCE")

AXES_FAILURE_LIMIT = 3
AXES_COOLOFF_TIME = lambda request: timedelta(minutes=5)  # noqa
AXES_LOCKOUT_PARAMETERS = [
    "username",
]
AXES_ENABLE_ADMIN = True

NINJA_DOCS_UI = os.environ.get("NINJA_DOCS_UI", "swagger")
LOGGING_MIDDLEWARE_SENSITIVE_URLS = [
    "/api-auth/login/",
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/password_change/",
    "/accounts/password_reset/",
    "/admin/login/",
    "/admin/logout/",
    "/api/token/",
    "/api/token/refresh/",
    "/api/token/verify/",
    "/portal/login/",
    "/api-auth/login/",
    "/portal/admin/",
]


MAX_ACTIVE_WEBHOOKS_PER_TYPE = os.getenv("MAX_ACTIVE_WEBHOOKS_PER_TYPE", 5)
