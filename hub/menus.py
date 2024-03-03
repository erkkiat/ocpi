from django.http import HttpRequest
from django.utils.translation import gettext as _

from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpiconnector.ocpi_identities import ocpi_platform
from util import reverse


def get_hub_menus(request: HttpRequest):
    def get_url(module, obj, action, criteria=True, namespace='admin') -> str:
        if criteria and request.user.has_perm(f'{namespace}:{module}.{obj}_{action}'):
            return reverse(f'{namespace}:{module}_{obj}_{action}')
        return ''

    sections = (
        dict(
            name='charge points',
            items=Location.objects.all(),
            icon='fa-charging-station',
            list_url=get_url('ocpi22', 'evse', 'changelist'),
            add_url=get_url('ocpi22', 'evse', 'add', ocpi_platform.is_cpo),
            extra_items=[
                dict(
                    url=reverse('admin:ocpi22_location_changelist'),
                    name=_('Locations list'),
                    icon='fa-map-marker-alt',
                ),
            ],
        ),
        dict(
            name='tariffs',
            items=Tariff.objects.exclude(archived=True).order_by('uid'),
            icon='fa-money-bill-wave',
            list_url=get_url('ocpi22', 'tariff', 'changelist'),
            add_url=get_url('ocpi22', 'tariff', 'add', ocpi_platform.is_cpo),
        ),
        dict(
            name='tokens',
            items=[],
            icon='fa-circle',
            list_url=get_url('ocpi22', 'token', 'changelist'),
            add_url=get_url('ocpi22', 'token', 'add', ocpi_platform.is_emsp),
            search_url=get_url('ocpi22', 'token', 'changelist'),
        ),
        dict(
            name='users',
            # items=User.objects.all().order_by('last_name', 'first_name') if request.user.has_perm('auth_user_changelist') else [],
            items=[],
            icon='fa-user',
            list_url=get_url('auth', 'user', 'changelist'),
            add_url=get_url('auth', 'user', 'add'),
            search_url=get_url('auth', 'user', 'changelist'),
            extra_items=[
                dict(
                    url=reverse('admin:gdpr_assist_personaldata_changelist'),
                    name=_('GDPR tools'),
                    icon='fa-user-secret',
                ),
            ],
        ),
        dict(
            name='sessions',
            items=Session.objects.none(),
            icon='fa-bolt',
            list_url=get_url('ocpi22', 'session', 'changelist'),
            add_url=get_url('ocpi22', 'session', 'add', criteria=False),
            search_url=get_url('ocpi22', 'session', 'changelist'),
            reporting_url='https://app.zoined.com/dashboards/6477',
            extra_items=[
                dict(
                    url=f"{reverse('admin:ocpi22_session_changelist')}?status__exact=ACTIVE",
                    name=_('{number} active sessions').format(
                        number=Session.objects.filter(status=Session.ACTIVE).count()
                    ),
                    icon='fa-bolt',
                ),
                dict(
                    url=reverse('admin:ocpi22_cdr_changelist'),
                    name=_('Billing records'),
                    icon='fa-money-bill-wave',
                ),
            ],
        ),
        dict(
            name='roaming',
            items=Credentials.objects.all(),
            icon='fa-handshake',
            list_url=get_url('ocpi22', 'credentials', 'changelist', namespace='hubadmin'),
            add_url=get_url('ocpi22', 'credentials', 'add', namespace='hubadmin'),
        ),
    )
    return sections
