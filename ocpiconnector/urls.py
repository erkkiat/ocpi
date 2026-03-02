from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from health_check import health_check_api

import ocpi22.cpo.tariff
from ocpi22 import msp
from ocpi22.msp.map import MapViewSet
from ocpi22.ocpi.api import (
    OCPIRouter,
    CredentialsViewSet,
    RootRouter,
    ClientInfoViewSet,
)
from ocpi22.cpo.api import (
    CPORouter,
    ChargePointViewSet,
    CpoStartWebhookViewSet,
    CpoStopWebhookViewSet,
    CpoReserveNowWebhookViewSet,
    InvoiceWebhookViewSet,
)

from ocpi22.models.credentials import new_connection
from ocpi22.msp.api import (
    MSPRouter,
    MspRoamingViewSet,
    MspTokenViewSet,
    MspAuthorizeWebhookViewSet,
    MspTariffQuickViewSet,
    MspChargePointStatusWebhookViewSet,
    MspSessionWebhookViewSet,
    MspInvoiceWebhookViewSet,
)
from ocpi22.credentials.versions import VersionsViewSet, BaseRouter
from ocpi22.views import home
from payment.views import PaymentViewSet
from settlement.views import CdrReportViews
from integrations.hubject.api import api as hubject_api
from ocpi22.cpo.api import api as cpo_locations_api
from ocpi22.payments.api import payments_ninja_api

ocpi_router = OCPIRouter()
ocpi_router.register(r"credentials/", CredentialsViewSet, basename="credentials")
ocpi_router.register(r"hubclientinfo/", ClientInfoViewSet, basename="clientinfo")

cpo_router = CPORouter()
cpo_router.register(
    r"v2/tariffs", ocpi22.cpo.tariff.SolidTariffViewSet, basename="solid-tariff"
)
cpo_router.register(r"v2/chargepoint", ChargePointViewSet, basename="chargepoint")
cpo_router.register(r"v2/webhook", CpoReserveNowWebhookViewSet, basename="cpo")
cpo_router.register(r"v2/webhook", CpoStartWebhookViewSet, basename="cpo-start")
cpo_router.register(r"v2/webhook", CpoStopWebhookViewSet, basename="cpo-stop")
cpo_router.register(r"v2/webhook", InvoiceWebhookViewSet, basename="cpo-invoicing")
cpo_router.register(r"v2/reports/billing", CdrReportViews, basename="billing")

msp_router = MSPRouter()
msp_router.register(r"roaming", MspRoamingViewSet, basename="roaming")
msp_router.register(r"token", MspTokenViewSet, basename="msp-token")
msp_router.register(r"tariff", MspTariffQuickViewSet, basename="msp-tariff")
msp_router.register(r"webhook", MspAuthorizeWebhookViewSet, basename="msp")
msp_router.register(
    r"webhook", MspChargePointStatusWebhookViewSet, basename="msp-status"
)
msp_router.register(r"webhook", MspSessionWebhookViewSet, basename="msp-session")
msp_router.register(r"webhook", MspInvoiceWebhookViewSet, basename="msp-invoicing")
msp_router.register(r"map", MapViewSet, basename="map")
msp_router.register(r"cdr", msp.api.CdrViewSet, basename="msp-cdr")
msp_router.register(r"payment", PaymentViewSet, basename="msp-payment")

root_router = RootRouter()

common_router = BaseRouter()
common_router.register(r"", VersionsViewSet, basename="base")


schema_view = get_schema_view(
    openapi.Info(
        title="SolidRoam Roaming API",
        default_version="v2",
        description="Your expressway to OCPI roaming",
        # terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="erkki.tapola@solidroam.com"),
        # license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=[permissions.DjangoObjectPermissions],
)

# urlpatterns = i18n_patterns(
urlpatterns = [
    path("", home),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.locations.urls")),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.ocpi.urls")),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.commands.urls")),
    re_path(
        r"^ocpi/(?P<version>[1-2.]+)/", include(ocpi_router.urls), name="ocpi-22-root"
    ),
    path("api/cpo/", include(cpo_router.urls), name="cpo-interface"),
    path("api/cpo/locations/", cpo_locations_api.urls),
    path("api/cpo/payments/", payments_ninja_api.urls),
    path("api/msp/v1/", include(msp_router.urls), name="msp-interface"),
    path("ocpi/", include(common_router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path(
        "portal/ocpi22/credentials/connection/new",
        new_connection,
        name="new-connection",
    ),
    path("portal/", admin.site.urls),
    path("_nested_admin/", include("nested_admin.urls")),
    path("api/hubject/2.3/", hubject_api.urls),
    path("/health-check", health_check_api.urls),
]

if settings.SERVE_STATIC_FILES or settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
