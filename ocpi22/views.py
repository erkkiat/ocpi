from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from ocpi22.credentials.versions import get_versions_dict
from ocpi22.issues import issue_count, get_issues
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.ocpi.util import OCPIResponse


@api_view(http_method_names=['GET'])
@permission_classes([AllowAny])
def home(request):
    # Return JSON when acting as the OCPI Versions endpoint
    if settings.RENDER_ONLY_JSON or (request.META and 'application/json' in request.META.get('HTTP_ACCEPT', '')):
        return OCPIResponse(get_versions_dict())

    return render(request, template_name='index.html')


def admin_index(request):
    context = dict(
        locations=Location.objects.all(),
        tariffs=Tariff.objects.exclude(archived=True).order_by('uid'),
        partners=Credentials.objects.all().order_by('valid', 'connection_status'),
        sessions=Session.objects.all().order_by('-start_date_time'),
    )
    ic(context)
    return render(request, template_name='admin/index.html', context=context)


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
