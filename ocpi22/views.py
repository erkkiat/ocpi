from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from ocpi22.credentials.versions import get_versions_dict
from ocpi22.issues import issue_count, get_issues
from ocpi22.ocpi.util import OCPIResponse
from ocpiconnector.ocpi_identities import ocpi_platform


@api_view(http_method_names=['GET'])
@permission_classes([AllowAny])
def home(request):
    # Return JSON when acting as the OCPI Versions endpoint
    if settings.RENDER_ONLY_JSON or (request.META and 'application/json' in request.META.get('HTTP_ACCEPT', '')):
        return OCPIResponse(get_versions_dict(request))

    # Let's assume the client is a browser
    context = dict(
        ocpi_platform=ocpi_platform
    )
    return render(request, template_name='index.html', context=context)


@staff_member_required
def issues(request, template_name='issues.html'):
    issues = get_issues()
    context = dict(
        user=request.user,
        issues=issues,
        issue_count=issue_count(issues),
    )
    return render(request, template_name, context)
