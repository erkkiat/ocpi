from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from ocpi22.credentials.versions import get_versions_dict
from ocpi22.issues import issue_count, get_issues
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.ocpi.util import OCPIResponse
from ocpiconnector.ocpi_identities import ocpi_platform


@api_view(http_method_names=['GET'])
@permission_classes([AllowAny])
def home(request):
    # Return JSON when acting as the OCPI Versions endpoint
    if settings.RENDER_ONLY_JSON or (request.META and 'application/json' in request.META.get('HTTP_ACCEPT', '')):
        return OCPIResponse(get_versions_dict())

    return render(request, template_name='index.html')


def admin_index(request):
    is_emsp = ocpi_platform.is_emsp
    is_cpo = ocpi_platform.is_cpo

    def get_url(module, obj, action, criteria=True) -> str:
        if criteria and request.user.has_perm(f'admin:{module}.{obj}_{action}'):
            return reverse(f'admin:{module}_{obj}_{action}')
        return ''

    sections = (
        dict(
            title=_('Locations'),
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
    return render(request, template_name='admin/index.html', context=dict(sections=sections))


@staff_member_required
def issues(request, template_name='issues.html'):
    issues_list = get_issues()
    context = dict(
        user=request.user,
        issues=issues_list,
        issue_count=issue_count(issues_list),
        is_nav_sidebar_enabled=True,
        has_permission=request.user.is_staff,
        site_url='/',
    )
    return render(request, template_name, context)
