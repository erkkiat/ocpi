from django.conf import settings
from django.conf.urls import include
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import path
from rest_framework.schemas import get_schema_view

from cars.views import CarsViewSet
from ocpi22 import msp
from ocpi22.msp.map import MapViewSet
from ocpi22.msp.user import UserViewSet
from ocpi22.ocpi.api import OCPIRouter, TokenViewSet, TariffViewSet, SessionViewSet, CdrViewSet, CredentialsViewSet, \
    RootRouter, ClientInfoViewSet, NoPremiumViewSet
from ocpi22.commands.commands import CommandsViewSet
from ocpi22.cpo.api import CPORouter, ChargePointViewSet, LocationQuickViewSet
from ocpi22.hub import CommandsHubViewSet

from ocpi22.locations.location import LocationViewSet
from ocpi22.models.credentials import new_connection
from ocpi22.msp.api import MSPRouter, MspRoamingViewSet
from ocpi22.credentials.versions import VersionsViewSet, BaseRouter
from ocpi22.views import home
from ocpiconnector import charger_simulator
from ocpiconnector.ocpi_identities import ocpi_platform

ocpi_router = OCPIRouter()
ocpi_router.register(r'credentials', CredentialsViewSet if settings.PREMIUM else NoPremiumViewSet,
                     basename='credentials')
ocpi_router.register(r'hubclientinfo', ClientInfoViewSet, basename='clientinfo')
ocpi_router.register(r'tokens', TokenViewSet)
ocpi_router.register(r'locations', LocationViewSet if settings.PREMIUM else NoPremiumViewSet, basename='location')
ocpi_router.register(r'tariffs', TariffViewSet if settings.PREMIUM else NoPremiumViewSet, basename='tariff')
ocpi_router.register(r'sessions', SessionViewSet)
ocpi_router.register(r'cdrs', CdrViewSet if settings.PREMIUM else NoPremiumViewSet, basename='cdr')
if ocpi_platform.is_hub:
    ocpi_router.register(r'commands', CommandsHubViewSet, basename='commands')
ocpi_router.register(r'commands', CommandsViewSet, basename='commands')

cpo_router = CPORouter()
# cpo_router.register(r'evses', CpoEvseViewSet, basename='cpo-evse')
# cpo_router.register(r'cdrs', CpoCdrViewSet)
# cpo_router.register(r'session', CpoSessionViewSet, basename='session')
cpo_router.register(r'location/quick', LocationQuickViewSet, basename='quick-location')
cpo_router.register(r'chargepoint', ChargePointViewSet, basename='chargepoint')

msp_router = MSPRouter()
msp_router.register(r'roaming', MspRoamingViewSet, basename='roaming')
msp_router.register(r'map', MapViewSet, basename='map')
msp_router.register(r'user', UserViewSet, basename='user')
msp_router.register(r'cdr', msp.user.CdrViewSet, basename='msp-cdr')
msp_router.register(r'cars', CarsViewSet, basename='msp-cars')

root_router = RootRouter()

common_router = BaseRouter()
common_router.register(r'', VersionsViewSet, basename='base')

urlpatterns = (
    # urlpatterns = i18n_patterns(
    path('', home),
    path('', include(root_router.urls), name='root-view'),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('ocpi/cpo/2.2/', include(ocpi_router.urls), name='ocpi-22-root'),
    path('api/cpo/v2/', include(cpo_router.urls), name='cpo-interface'),
    path('api/msp/v1/', include(msp_router.urls), name='msp-interface'),
    path('ocpi/', include(common_router.urls)),
    path('simulator/', include(charger_simulator.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/ocpi22/credentials/connection/new', new_connection, name='new-connection'),
    path('admin/', admin.site.urls),
    path('_nested_admin/', include('nested_admin.urls')),
    path('openapi', get_schema_view(
        title="OCPI Connector",
        description="OpenAPI schemas for ChargerHub.EU OCPI Connector",
        version="1.0.0"
    ), name='openapi-schema'),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
)
