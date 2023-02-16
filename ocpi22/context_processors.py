import os

import cachetools
from django.urls import reverse
from django.utils.translation import gettext as _

from ocpi22.issues import issue_count, get_issues
from ocpiconnector.ocpi_identities import ocpi_identities, ocpi_platform


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


@cachetools.cached(cache={})
def _get_environment():
    return dict(
        header_color=os.environ.get('HEADER_COLOR'),
        roles=" / ".join([f'{key}: {value}' for key, value in ocpi_identities.items()]),
        admin_menu=get_admin_menu(),
        general_message=os.environ.get('GENERAL_MESSAGE'),
        ocpi_platform=ocpi_platform,
    )


def export_environment_variables(_request):
    return _get_environment()


def export_issue_count(_request):
    return dict(
        issue_count=issue_count(get_issues())
    )
