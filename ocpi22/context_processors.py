import os

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ocpi22.issues import issue_count, get_issues
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpiconnector.ocpi_identities import ocpi_platform
from ocpi22.payments.models import Terminal
from webhooks.models import Webhook


# @cachetools.cached(cache={})  # Cannot cache the recent activity
def _get_environment(request):
    is_emsp = ocpi_platform.is_emsp
    is_cpo = ocpi_platform.is_cpo

    def get_url(module, obj, action, criteria=True) -> str:
        if criteria and request.user.has_perm(f"admin:{module}.{obj}_{action}"):
            return reverse(f"admin:{module}_{obj}_{action}")
        return ""

    result = dict(
        # csrf_token=get_token(request),  # This is not needed
        general_message=os.environ.get("GENERAL_MESSAGE"),
        cpo_api=settings.CPO_API,
        msp_api=settings.MSP_API,
        ocpi_platform=ocpi_platform,
        recent_activity=Session.objects.all().order_by("-start_date_time"),
        date_now=timezone.now(),
    )
    result["sections"] = (
        dict(
            name="charge points",
            items=Location.objects.all(),
            icon="fa-charging-station",
            list_url=get_url("ocpi22", "evse", "changelist"),
            add_url=get_url("ocpi22", "evse", "add", is_cpo),
            extra_items=[
                dict(
                    url=reverse("admin:ocpi22_location_changelist"),
                    name=_("Locations list"),
                    icon="fa-map-marker-alt",
                ),
            ],
        ),
        dict(
            name="tariffs",
            items=Tariff.objects.exclude(archived=True).order_by("uid"),
            icon="fa-money-bill-wave",
            list_url=get_url("ocpi22", "tariff", "changelist"),
            add_url=get_url("ocpi22", "tariff", "add", is_cpo),
        ),
        dict(
            name="tokens",
            items=[],
            icon="fa-circle",
            list_url=get_url("ocpi22", "token", "changelist"),
            add_url=get_url("ocpi22", "token", "add", is_emsp),
            search_url=get_url("ocpi22", "token", "changelist"),
        ),
        dict(
            name="users",
            # items=User.objects.all().order_by('last_name', 'first_name') if request.user.has_perm('auth_user_changelist') else [],
            items=[],
            icon="fa-user",
            list_url=get_url("auth", "user", "changelist"),
            add_url=get_url("auth", "user", "add"),
            search_url=get_url("auth", "user", "changelist"),
            extra_items=[
                dict(
                    url=reverse("admin:gdpr_assist_personaldata_changelist"),
                    name=_("GDPR tools"),
                    icon="fa-user-secret",
                ),
            ],
        ),
        dict(
            name="sessions",
            items=Session.objects.none(),
            icon="fa-bolt",
            list_url=get_url("ocpi22", "session", "changelist"),
            add_url=get_url("ocpi22", "session", "add", criteria=False),
            search_url=get_url("ocpi22", "session", "changelist"),
            reporting_url="https://app.zoined.com/dashboards/6477",
            extra_items=[
                dict(
                    url=f"{reverse('admin:ocpi22_session_changelist')}?status__exact=ACTIVE",
                    name=_("{number} active sessions").format(
                        number=Session.objects.filter(status=Session.ACTIVE).count()
                    ),
                    icon="fa-bolt",
                ),
                dict(
                    url=reverse("admin:ocpi22_cdr_changelist"),
                    name=_("Billing records"),
                    icon="fa-money-bill-wave",
                ),
            ],
        ),
        dict(
            name="customers" if ocpi_platform.is_hub else "roaming partners",
            items=Credentials.objects.all().order_by(
                "-connection_status", "-last_connection"
            ),
            icon="fa-handshake",
            list_url=get_url("ocpi22", "credentials", "changelist"),
            add_url=get_url("ocpi22", "credentials", "add"),
        ),
        dict(
            name="webhooks",
            items=Webhook.objects.all(),
            icon="fa-exchange-alt",
            list_url=get_url("webhooks", "webhook", "changelist"),
            add_url=get_url("webhooks", "webhook", "add"),
            extra_items=[
                dict(
                    url=reverse("admin:webhooks_webhookevent_changelist"),
                    name=_("Webhook Events"),
                    icon="fa-list",
                ),
                dict(
                    url=reverse("admin:webhooks_webhookauth_changelist"),
                    name=_("Webhook Auth"),
                    icon="fa-key",
                ),
            ],
        ),
        dict(
            name="payments",
            items=Terminal.objects.all(),
            icon="fa-credit-card",
            list_url=get_url("ocpi22", "terminal", "changelist"),
            add_url="",
            extra_items=[
                dict(
                    url=reverse("admin:ocpi22_terminal_changelist"),
                    name=_("Payment Terminals"),
                    icon="fa-cash-register",
                ),
                dict(
                    url=reverse("admin:ocpi22_financialadviceconfirmation_changelist"),
                    name=_("Financial Advice Confirmations"),
                    icon="fa-file-invoice-dollar",
                ),
            ],
        ),
    )
    return result


def export_environment_variables(request):
    return _get_environment(request)


def export_issue_count(_request):
    return dict(issue_count=issue_count(get_issues()))
