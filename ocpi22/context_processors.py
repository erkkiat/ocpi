import os

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.translation import gettext as _

from ocpi22.issues import issue_count, get_issues
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpiconnector.ocpi_identities import ocpi_platform


def get_admin_menu() -> list:
    menuitems = (
        ('', _('Infrastructure')),
        ('admin:ocpi22_location_changelist', _('Locations')),
        ('admin:ocpi22_evse_changelist', _('Chargers')),

        ('', _('Users')),
        ('admin:auth_user_changelist', _('Users')),
        ('admin:auth_group_changelist', _('Groups')),
        ('admin:gdpr_assist_personaldata_changelist', _('GDPR Personal Data')),

        ('', _('Finance')),
        ('admin:ocpi22_cdr_changelist', _('Billing')),
        ('admin:payment_payment_changelist', _('Payments')),
        ('admin:ocpi22_session_changelist', _('Sessions')),
        ('admin:ocpi22_tariff_changelist', _('Tariffs')),
        ('admin:ocpi22_defaulttariffs_changelist', _('Default Tariffs')),
        ('admin:ocpi22_authorization_changelist', _('Charge Authorizations')),

        ('', _('Identification')),
        ('admin:ocpi22_token_changelist', _('Tokens')),
        ('admin:ocpi22_credentials_changelist', _('Credentials')),

        ('', _('Problem Resolution')),
        ('issues', _('Issues')),
        ('admin:ocpi22_logentry_changelist', _('Log entries')),
    )
    return [dict(url=reverse(viewname) if viewname else "#", name=_(name)) for viewname, name in menuitems]


# @cachetools.cached(cache={})
def _get_environment(request):
    is_emsp = ocpi_platform.is_emsp
    is_cpo = ocpi_platform.is_cpo

    def get_url(module, obj, action, criteria=True) -> str:
        if criteria and request.user.has_perm(f'admin:{module}.{obj}_{action}'):
            return reverse(f'admin:{module}_{obj}_{action}')
        return ''

    return dict(
        # header_color=os.environ.get('HEADER_COLOR'),
        # roles=" / ".join([f'{key}: {value}' for key, value in ocpi_identities.items()]),
        # admin_menu=get_admin_menu(),
        general_message=os.environ.get('GENERAL_MESSAGE'),
        ocpi_platform=ocpi_platform,
        sections=(
            dict(
                title=_('Charge Points'),
                items=Location.objects.all(),
                icon='fa-charging-station',
                list_url=get_url('ocpi22', 'evse', 'changelist'),
                add_url=get_url('ocpi22', 'evse', 'add', is_cpo),
            ),
            dict(
                title=_('Tariffs'),
                items=Tariff.objects.exclude(archived=True).order_by('uid'),
                icon='fa-money-bill-wave',
                list_url=get_url('ocpi22', 'tariff', 'changelist'),
                add_url=get_url('ocpi22', 'tariff', 'add', is_cpo),
            ),
            dict(
                title=_('Tokens'),
                items=[],
                icon='fa-circle',
                list_url=get_url('ocpi22', 'token', 'changelist'),
                add_url=get_url('ocpi22', 'token', 'add', is_emsp),
            ),
            dict(
                title=_('Customers'),
                items=User.objects.all().order_by('last_name', 'first_name'),
                icon='fa-user',
                list_url=get_url('auth', 'user', 'changelist'),
                add_url=get_url('auth', 'user', 'add'),
            ),
            dict(
                title=_('Sessions'),
                items=Session.objects.all().order_by('-start_date_time'),
                icon='fa-bolt',
                list_url=get_url('ocpi22', 'session', 'changelist'),
                add_url=get_url('ocpi22', 'session', 'add', criteria=False),
            ),
            dict(
                title=_('Partners'),
                items=Credentials.objects.all().order_by('valid', 'connection_status'),
                icon='fa-handshake',
                list_url=get_url('ocpi22', 'credentials', 'changelist'),
                add_url=get_url('ocpi22', 'credentials', 'add'),
            ),
        )

    )


def export_environment_variables(request):
    return _get_environment(request)


def export_issue_count(_request):
    return dict(
        issue_count=issue_count(get_issues())
    )
