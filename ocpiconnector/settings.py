# Django settings for ocpiconnector project.
import os
from datetime import datetime

import sentry_sdk
from django.conf.locale.en import formats as locale_formats
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

# Install icecream globally, no need for local imports
from icecream import install

install()

ic.configureOutput(includeContext=True)
# ic.disable()

TRUE_OPTIONS = (1, '1', True, 'True', 'true')


def _env_bool(key, default=False) -> bool:
    return bool(os.environ.get(key, default) in TRUE_OPTIONS)


RENDER_ONLY_JSON = _env_bool('RENDER_ONLY_JSON', False)

DEBUG = _env_bool('DEBUG', False)
TEST = _env_bool('TEST', False)

if not DEBUG:
    sentry_sdk.init(
        dsn=os.environ.get('SENTRY_DSN'),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.2,
    )

DATETIME_FORMAT = os.environ.get('DATETIME_FORMAT', "%d.%m.%Y %H:%M")
DATE_FORMAT = os.environ.get('DATE_FORMAT', "%d.%m.%Y")
locale_formats.DATETIME_FORMAT = os.environ.get('DATETIME_FORMAT_LOCALE', "D j.n.Y H:i")
DECIMAL_SEPARATOR = os.environ.get('DECIMAL_SEPARATOR', ',')
DEFAULT_CURRENCY = os.environ.get('DEFAULT_CURRENCY', 'EUR')

PREMIUM = _env_bool('PREMIUM', False)

PERFORMANCE_TEST = _env_bool('PERFORMANCE_TEST', False)
CPO_SIMULATOR = _env_bool('CPO_SIMULATOR', False)

ALLOW_ADMIN_DELETE_AND_CHANGE = _env_bool('ALLOW_ADMIN_DELETE_AND_CHANGE', False)

# Complete expiration of access at 00:00 on the specified date
expires_on_str = os.environ.get('EXPIRES_ON')
EXPIRES_ON = datetime.strptime(expires_on_str, '%Y-%m-%d') if expires_on_str else None
WARN_BEFORE_DAYS = 3

# Philippines
# DATE_FORMAT = '%m/%d/%Y'
# DATETIME_FORMAT = '%m/%d/%Y, %I:%M %p'
# DECIMAL_SEPARATOR = '.'
# DEFAULT_CURRENCY = 'PHP'
# DATETIME_FORMAT_LOCALE = 'n/j/Y h:i a'

APPEND_SLASH = False  # Accept requests with no trailing slash
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # Allow more than 1000 fields in POST requests
TEMPLATE_DEBUG = DEBUG
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY and DEBUG:
    SECRET_KEY = '1234567890'
assert SECRET_KEY, 'Please set a SECRET_KEY in environment'
SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT')
REDIS_URL = os.environ.get('REDIS_URL', os.environ.get('REDISCLOUD_URL'))
TWILIO_API_KEY = os.environ.get('TWILIO_API_KEY')

# Send updates to partners who we have Credentials for
SEND_UPDATES = _env_bool('SEND_UPDATES', True)
UPDATES_DISABLED = 'Updates have been disabled using one of the environment variables SEND_UPDATES or PREMIUM.'
SERVE_STATIC_FILES = _env_bool('SERVE_STATIC_FILES', True)

REMOTE_COMMAND_EXPIRATION = os.environ.get('REMOTE_COMMAND_EXPIRATION', 2 * 60)

# Use the builtin account functionality and require a wallet balance when user wants to charge
USE_ACCOUNTS = _env_bool('USE_ACCOUNTS', False)
REQUIRE_WALLET_BALANCE = bool(_env_bool('REQUIRE_WALLET_BALANCE', True) and USE_ACCOUNTS)

OCPI_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
OCPI_22_URL = '/ocpi/2.2/'
OCPI_221_URL = '/ocpi/2.2.1/'

# How often to check that other party is alive
STILL_ALIVE_FREQUENCY = os.environ.get('STILL_ALIVE_FREQUENCY', 60 * 5)

# How long can a charger be reserved
MAXIMUM_RESERVATION = os.environ.get('MAXIMUM_RESERVATION', 60 * 30)

# Send updates asynchronously using Celery
BACKGROUND_SEND = _env_bool('BACKGROUND_SEND', True)

ADMINS = [('Erkki Tapola', 'erkki.tapola@chargerhub.eu')]
MANAGERS = ADMINS

TIMEOUT_FOR_COMMANDS = 2 * 60

HOSTNAME = os.environ['HOSTNAME']
SCHEME = os.environ.get('SCHEME', 'https')

OCPI_SPECIFICATION_URL = 'https://github.com/ocpi/ocpi/blob/release-2.2-bugfixes/'

# These are in the OCPI 2.2 specification, so don't change them
OCPI_22_MAX_ADDRESS_LENGTH = 45
OCPI_22_MAX_TIME_ZONE_LENGTH = 64
OCPI_22_MAX_UID_LENGTH = 36

PUBLIC_VIEWS = ['user-register']


def parse_jawsdb_maria_url(url):
    protocol, url = url.split('://')
    assert (protocol == 'mysql')
    credentials, connection = url.split('@')
    userid, password = credentials.split(':')
    connection, database = connection.split('/')
    host, port = connection.split(':')
    return dict(default={
        'ENGINE': 'django.db.backends.mysql',
        'NAME': database,
        'USER': userid,
        'PASSWORD': password,
        'HOST': host,
        'PORT': port,
        'OPTIONS': {
            'sql_mode': 'traditional',
        }
    })


JAWSDB_MARIA_URL = os.environ.get('JAWSDB_MARIA_URL',
                                  os.environ.get('JAWSDB_URL', None))
if JAWSDB_MARIA_URL:
    # We're running on Heroku
    DATABASES = (parse_jawsdb_maria_url(JAWSDB_MARIA_URL))
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',  # Add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
            'NAME': os.environ.get('DATABASE_FILE', 'dev.sqlite3'),  # Or path to database file if using sqlite3.
            # The following settings are not used with sqlite3:
            'USER': '',
            'PASSWORD': '',
            'HOST': '',  # Empty for localhost through domain sockets or '127.0.0.1' for localhost through TCP.
            'PORT': '',  # Set to empty string for default.
            'ATOMIC_REQUESTS': True,
        }
    }

# # Add a new database to log GDPR actions
# DATABASES.update({
#     'gdpr_log': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': os.path.join(BASE_DIR, 'gdpr-log.sqlite3'),
#     },
# })

DATABASES.update(
    {'gdpr_log': DATABASES.get('default')}
)

# GDPR_LOG_DATABASE_NAME = 'default'
# DATABASE_ROUTERS = ['gdpr_assist.routers.EventLogRouter']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if os.environ.get('_system_arch') == 'arm64':  # This is an M1 or M2 chip, need to hack mysql to work
    print("*** Looks like this is an Apple M1/M2, let's hack the MySQL connection to work")
    import pymysql

    # Fake PyMySQL's version and install as MySQLdb
    # https://adamj.eu/tech/2020/02/04/how-to-use-pymysql-with-django/
    pymysql.version_info = (1, 4, 2, "final", 0)
    pymysql.install_as_MySQLdb()


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
    components = hostname.split('.')
    return [
        f'{components[0]}.{x}'
        for x in ['herokuapp.com', 'ocpiconnector.com', 'roamingconnector.com', 'ocpiguide.com', 'chargerhub.eu',
                  'solidroam.com']
    ]


ALLOWED_HOSTS = [
                    'localhost', '127.0.0.1', 'testserver.test',
                ] + hostname_variants(HOSTNAME)

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'UTC'  # DO NOT CHANGE THIS, or the OCPI date query parameters will not match

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = os.environ.get('LANGUAGE_CODE', 'en')

LANGUAGES = [
    ('en', _('English')),
    ('nl', _('Dutch, Flemish')),
    ('fr', _('French')),
    ('de', _('German')),
    ('es', _('Spanish')),
    ('it', _('Italian')),
    ('pt', _('Portuguese')),
    ('lb', _('Luxembourgish')),
    ('cy', _('Welsh')),
    ('ga', _('Irish')),

    ('be', _('Belarusian')),
    ('bg', _('Bulgarian')),
    ('ro', _('Romanian')),
    ('bs', _('Bosnian')),
    ('mk', _('Macedonian')),
    ('sq', _('Albanian')),
    ('sr', _('Serbian')),
    ('tr', _('Turkish')),
    ('uk', _('Ukrainian')),
    ('el', _('Greek')),

    ('pl', _('Polish')),
    ('hu', _('Hungarian')),
    ('cs', _('Czech')),
    ('sk', _('Slovak')),
    ('sl', _('Slovenian')),

    ('fi', _('Finnish')),
    ('nn', _('Nynorsk')),
    ('da', _('Danish')),
    ('sv', _('Swedish')),
    ('is', _('Icelandic')),

    ('et', _('Estonian')),
    ('lt', _('Lithuanian')),
    ('lv', _('Latvian')),

    ('af', _('Afrikans')),
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
USE_TZ = False  # DO NOT CHANGE THIS, or the OCPI date query parameters will not match

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = ''

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = ''

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
STATIC_URL = os.environ.get('EDGE_URL', '') + '/static/'

if os.environ.get('LOCAL_STATIC') and False:
    STATIC_ROOT = os.path.join(BASE_DIR, 'ocpiconnector/static')
else:
    STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"

# Additional locations of static files
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "ocpiconnector/static"),
]

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    # 'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
    #     'django.template.loaders.eggs.Loader',
)

MIDDLEWARE = [
    'ocpi22.middleware.ErrorLoggingMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # Make sure this stays above OCPIHubMiddleware
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'ocpi22.middleware.UserActivityMiddleware',
]

if 'MOESIF_APPLICATION_ID' in os.environ:
    MIDDLEWARE.append('moesifdjango.middleware.moesif_middleware')

if EXPIRES_ON:
    MIDDLEWARE.append('ocpi22.middleware.EnabledUntilMiddleware')

if os.environ.get('DEBUG_MIDDLEWARE') in TRUE_OPTIONS:
    MIDDLEWARE.append('ocpi22.middleware.DebugMiddleware')

if os.environ.get('HUB'):
    # Running as a hub, start acting like one
    MIDDLEWARE.append('ocpi22.middleware.OCPIHubMiddleware')

ROOT_URLCONF = 'ocpiconnector.urls'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # 'django.contrib.admindocs',
    'ocpi22',
    'ocpiconnector',
    'cars',
    'settlement',
    'django.contrib.admin',
    # 'whitenoise',
    'rest_framework',
    'django_filters',
    'nested_admin',
    'oauth2_provider',
    'crispy_forms',
    'gdpr_assist',
    'payment',
    'drf_yasg',
]

#
# CORS
#

try:
    CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', False)
    if not CORS_ALLOW_ALL_ORIGINS:
        CORS_ALLOWED_ORIGINS = [x for x in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if x]

    from corsheaders.defaults import default_headers

    CORS_ALLOW_HEADERS = (
        *default_headers,
        "access-control-allow-origin",
    )

    MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
    INSTALLED_APPS = ['corsheaders'] + INSTALLED_APPS

except ModuleNotFoundError:
    print('Unable to load CORS settings, CORS will be disabled')
    CORS_ALLOW_ALL_ORIGINS = False

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'ocpiconnector.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'ocpi22.context_processors.export_environment_variables',
                'ocpi22.context_processors.export_issue_count',
                'django.template.context_processors.i18n',
            ],
        },
    },
]

# Todo: Use Redis as Messages backend

MESSAGE_STORAGE = 'ocpiconnector.util.SessionDedupStorage'  # Removes duplicate messages, like the OCPI 2.2 explanations
SESSION_SERIALIZER = 'django.contrib.sessions.serializers.JSONSerializer'

# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
# See http://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        },
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    }
}

# OAuth2
LOGIN_URL = '/admin/login/'

OAUTH2_PROVIDER = {
    # this is the list of available scopes
    'SCOPES': {'read': 'Read scope', 'write': 'Write scope', 'groups': 'Access to your groups'}
}

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.coreapi.AutoSchema',
    'DEFAULT_PERMISSION_CLASSES': [
        'ocpi22.ocpi.auth.OCPIPermission'
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'oauth2_provider.contrib.rest_framework.OAuth2Authentication',
    ),
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ],
    'DEFAULT_METADATA_CLASS': 'ocpi22.util.MyMetadata',
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        # 'rest_framework_csv.renderers.CSVRenderer',
    ],
}

if not RENDER_ONLY_JSON:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'].append('rest_framework.renderers.BrowsableAPIRenderer')

# Celery Configuration Options
# CELERY_TIMEZONE = "Finland/Helsinki"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = TIMEOUT_FOR_COMMANDS - 1
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TASK_DEFAULT_QUEUE = os.environ.get('CELERY_QUEUE', 'default')

if TEST:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# Moesif API analytics

def identifyUser(req, res):
    if req.user and req.user.is_authenticated:
        return req.user.username
    else:
        return None


MOESIF_MIDDLEWARE = {
    'APPLICATION_ID': os.environ.get('MOESIF_APPLICATION_ID'),
    'CAPTURE_OUTGOING_REQUESTS': True,  # Set to True to also capture outgoing calls to 3rd parties.
    'IDENTIFY_USER': identifyUser  # Optional hook to link API calls to users
}

CRISPY_TEMPLATE_PACK = 'bootstrap4'

MESSAGE_TAGS = {
    messages.DEBUG: 'alert-secondary',
    messages.INFO: 'alert-info',
    messages.SUCCESS: 'alert-success',
    messages.WARNING: 'alert-warning',
    messages.ERROR: 'alert-danger',
}

