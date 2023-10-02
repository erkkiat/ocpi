from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.urls import reverse, translate_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, check_for_language, LANGUAGE_SESSION_KEY
from django.views.i18n import LANGUAGE_QUERY_PARAMETER
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
    accept = request.META.get('HTTP_ACCEPT', '')
    content_type = request.META.get('HTTP_CONTENT_TYPE', '')
    expected_type = 'application/json'
    if settings.RENDER_ONLY_JSON or expected_type in accept or expected_type in content_type:
        return OCPIResponse(get_versions_dict())

    return render(request, template_name='index.html')


def admin_index(request):
    return render(request, template_name='admin/index.html')


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


def set_language(request):
    """
    Redirect to a given URL while setting the chosen language in the session
    (if enabled) and in a cookie. The URL and the language code need to be
    specified in the request parameters.

    Since this view changes how the user will see the rest of the site, it must
    only be accessed as a POST request. If called as a GET request, it will
    redirect to the page in the request (the 'next' parameter) without changing
    any state.
    """
    next_url = request.POST.get('next', request.GET.get('next'))
    if (
        (next_url or request.accepts('text/html')) and
        not url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        next_url = request.META.get('HTTP_REFERER')
        if not url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            next_url = '/'
    response = HttpResponseRedirect(next_url) if next_url else HttpResponse(status=204)
    if request.method == 'GET':
        lang_code = request.GET.get(LANGUAGE_QUERY_PARAMETER)
        if lang_code and check_for_language(lang_code):
            if next_url:
                next_trans = translate_url(next_url, lang_code)
                if next_trans != next_url:
                    response = HttpResponseRedirect(next_trans)
            if hasattr(request, 'session'):
                request.session[LANGUAGE_SESSION_KEY] = lang_code
            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME, lang_code,
                max_age=settings.LANGUAGE_COOKIE_AGE,
                path=settings.LANGUAGE_COOKIE_PATH,
                domain=settings.LANGUAGE_COOKIE_DOMAIN,
                secure=settings.LANGUAGE_COOKIE_SECURE,
                httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
                samesite=settings.LANGUAGE_COOKIE_SAMESITE,
            )
    return response
