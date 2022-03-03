# Django settings for ocpiconnector project.
import os
from django.conf.locale.en import formats as locale_formats


def _env_bool(key, default=False) -> bool:
    TRUE_OPTIONS = (1, '1', True, 'True', 'true')
    return bool(os.environ.get(key, default) in TRUE_OPTIONS)


DATETIME_FORMAT = "%d.%m.%Y %H:%M"
locale_formats.DATETIME_FORMAT = "D j.n.Y H:i"
DECIMAL_SEPARATOR = os.environ.get('DECIMAL_SEPARATOR', ',')
DEFAULT_CURRENCY = os.environ.get('DEFAULT_CURRENCY', 'EUR')

APPEND_SLASH = False  # Accept requests with no trailing slash
DEBUG = _env_bool('DEBUG', False)
TEMPLATE_DEBUG = DEBUG
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY and DEBUG:
    SECRET_KEY = '1234567890'
assert SECRET_KEY, 'Please set a SECRET_KEY in environment'
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT')

# Send updates to partners who we have Credentials for
SEND_UPDATES = _env_bool('SEND_UPDATES', True)
UPDATES_DISABLED = 'Updates have been disabled using the environment variable SEND_UPDATES.'

# How often to check that other party is alive
STILL_ALIVE_FREQUENCY = os.environ.get('STILL_ALIVE_FREQUENCY', 60 * 5)

# Send updates asynchronously using Celery
BACKGROUND_SEND = _env_bool('BACKGROUND_SEND', True)

ADMINS = [('Erkki Tapola', 'erkki.tapola@chargerhub.eu')]
MANAGERS = ADMINS

TIMEOUT_FOR_COMMANDS = 2 * 60

HOSTNAME = os.environ['HOSTNAME']

OCPI_SPECIFICATION_URL = 'https://github.com/ocpi/ocpi/blob/release-2.2-bugfixes/'


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
    DATABASES = parse_jawsdb_maria_url(JAWSDB_MARIA_URL)
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts
def hostname_variants(hostname):
    """
    >>> hostname_variants('testi10-ocpi.herokuapp.com')
    ['testi10-ocpi.herokuapp.com', 'testi10-ocpi.ocpiconnector.com', 'testi10-ocpi.roamingconnector.com', 'testi10-ocpi.ocpiguide.com', 'testi10-ocpi.chargerhub.eu']
    >>> hostname_variants('cpo-ocpi.ocpiconnector.com')
    ['cpo-ocpi.herokuapp.com', 'cpo-ocpi.ocpiconnector.com', 'cpo-ocpi.roamingconnector.com', 'cpo-ocpi.ocpiguide.com', 'cpo-ocpi.chargerhub.eu']
    >>> hostname_variants('cpo')
    ['cpo.herokuapp.com', 'cpo.ocpiconnector.com', 'cpo.roamingconnector.com', 'cpo.ocpiguide.com', 'cpo.chargerhub.eu']
    """
    components = hostname.split('.')
    return [
        f'{components[0]}.{x}'
        for x in ['herokuapp.com', 'ocpiconnector.com', 'roamingconnector.com', 'ocpiguide.com', 'chargerhub.eu']
    ]


ALLOWED_HOSTS = [
                    'localhost', '127.0.0.1',
                ] + hostname_variants(HOSTNAME)

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'UTC'  # DO NOT CHANGE THIS, or the OCPI date query parameters will not match

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = False

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
    #    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
    #     'django.template.loaders.eggs.Loader',
)

MIDDLEWARE = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 'ocpi22.middleware.DebugMiddleware',
)

ROOT_URLCONF = 'ocpiconnector.urls'

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
                # 'django.template.context_processors.i18n',
            ],
        },
    },
]

# Todo: Use Redis as Messages backend

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 'django.contrib.admindocs',
    'ocpi22',
    'ocpiconnector',
    'django.contrib.admin',
    'whitenoise',
    'rest_framework',
    'django_filters',
    'nested_admin',
)

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
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    }
}

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'ocpi22.auth.OCPIPermission'
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ],
}

# Celery Configuration Options
# CELERY_TIMEZONE = "Finland/Helsinki"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = TIMEOUT_FOR_COMMANDS - 1
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
