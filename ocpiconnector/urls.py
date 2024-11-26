from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, re_path
from django.views.i18n import set_language
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from hub.admin_sites import hub_admin_site
from hub.urls import urlpatterns as hub_urls

from ocpi22 import msp, views
import ocpi22.cpo.tariff
from ocpi22.msp.map import MapViewSet
from ocpi22.msp.user import UserViewSet
from ocpi22.ocpi.api import (
    OCPIRouter,
    CredentialsViewSet,
    RootRouter,
    ClientInfoViewSet,
)
from ocpi22.cpo.api import (
    CPORouter,
    ChargePointViewSet,
    LocationQuickViewSet,
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
from settlement.views import InvoiceReportViews
from webhooks.urls import urlpatterns as webhooks_urls

ocpi_router = OCPIRouter()
ocpi_router.register(r"credentials/", CredentialsViewSet, basename="credentials")
ocpi_router.register(r"hubclientinfo/", ClientInfoViewSet, basename="clientinfo")

cpo_router = CPORouter()
cpo_router.register(r"location/quick", LocationQuickViewSet, basename="quick-location")
cpo_router.register(
    r"tariff/quick", ocpi22.cpo.tariff.TariffQuickViewSet, basename="quick-tariff"
)
cpo_router.register(r"chargepoint", ChargePointViewSet, basename="chargepoint")
cpo_router.register(r"webhook", CpoReserveNowWebhookViewSet, basename="cpo")
cpo_router.register(r"webhook", CpoStartWebhookViewSet, basename="cpo-start")
cpo_router.register(r"webhook", CpoStopWebhookViewSet, basename="cpo-stop")
cpo_router.register(r"webhook", InvoiceWebhookViewSet, basename="cpo-invoicing")
cpo_router.register(r"reports/billing", InvoiceReportViews, basename="billing")

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
msp_router.register(r"user", UserViewSet, basename="user")
msp_router.register(r"cdr", msp.user.CdrViewSet, basename="msp-cdr")
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
    path("18n/", include("django.conf.urls.i18n")),
    path("lang/", set_language, name="admin_set_language"),
    path("", home),
    path("", include(root_router.urls), name="root-view"),
    path("hub/", include(hub_urls)),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.locations.urls")),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.ocpi.urls")),
    re_path(r"^ocpi/(?P<version>[1-2.]+)/", include("ocpi22.commands.urls")),
    re_path(
        r"^ocpi/(?P<version>[1-2.]+)/", include(ocpi_router.urls), name="ocpi-22-root"
    ),
    path("api/cpo/v2/", include(cpo_router.urls), name="cpo-interface"),
    path("api/msp/v1/", include(msp_router.urls), name="msp-interface"),
    path("webhooks/", include(webhooks_urls)),
    path("ocpi/", include(common_router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    # JWT token operations
    # path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path(
        "admin/ocpi22/credentials/connection/new", new_connection, name="new-connection"
    ),
    path("admin/", admin.site.urls),
    path("hubadmin/", hub_admin_site.urls),
    path("issues/", views.issues, name="issues"),
    path("_nested_admin/", include("nested_admin.urls")),
    path(
        "swagger<format>/", schema_view.without_ui(cache_timeout=0), name="schema-json"
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    # path("__debug__/", include("debug_toolbar.urls")),
]

if settings.SERVE_STATIC_FILES or settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
