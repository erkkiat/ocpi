import os

import cachetools
from django.urls import reverse
from django.utils.translation import gettext as _

from ocpi22.issues import issue_count, get_issues
from ocpiconnector.ocpi_identities import ocpi_identities


def get_admin_menu() -> list:
    menuitems = (
        ('', 'Infrastructure'),
        ('admin:ocpi22_location_changelist', 'Locations'),
        ('admin:ocpi22_evse_changelist', 'Chargers'),

        ('', 'Users'),
        ('admin:auth_user_changelist', 'Users'),
        ('admin:auth_group_changelist', 'Groups'),
        ('admin:gdpr_assist_personaldata_changelist', 'GDPR Personal Data'),

        ('', 'Finance'),
        ('admin:ocpi22_cdr_changelist', 'Billing'),
        ('admin:payment_payment_changelist', 'Payments'),
        ('admin:ocpi22_session_changelist', 'Sessions'),
        ('admin:ocpi22_tariff_changelist', 'Tariffs'),
        ('admin:ocpi22_defaulttariffs_changelist', 'Default Tariffs'),
        ('admin:ocpi22_authorization_changelist', 'Charge Authorizations'),

        ('', 'Other'),
        ('admin:ocpi22_token_changelist', 'Tokens'),
        ('admin:ocpi22_credentials_changelist', 'Credentials'),

        ('', 'Problem Resolution'),
        ('issues', 'Issues'),
        ('admin:ocpi22_logentry_changelist', 'Log entries'),
    )
    return [dict(url=reverse(viewname) if viewname else "#", name=_(name)) for viewname, name in menuitems]


@cachetools.cached(cache={})
def _get_environment():
    return dict(
        header_color=os.environ.get('HEADER_COLOR'),
        roles=" / ".join([f'{key}: {value}' for key, value in ocpi_identities.items()]),
        admin_menu=get_admin_menu(),
    )


def export_environment_variables(_request):
    return _get_environment()


def export_issue_count(_request):
    return dict(
        issue_count=issue_count(get_issues())
    )
