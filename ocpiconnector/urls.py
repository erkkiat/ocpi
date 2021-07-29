from django.conf.urls import include
from django.contrib import admin
from django.urls import path
from rest_framework.schemas import get_schema_view

from ocpi22.api import OCPIRouter, TokenViewSet, TariffViewSet, SessionViewSet, CdrViewSet, CredentialsViewSet
from ocpi22.commands import CommandsViewSet
from ocpi22.cpo_api import CPORouter, \
    CpoEvseViewSet, \
    SessionViewSet as CpoSessionViewSet, LocationQuickViewSet

# CdrViewSet as CpoCdrViewSet
from ocpi22.location import LocationViewSet, EvseViewSet
from ocpi22.versions import VersionsViewSet, BaseRouter
from ocpiconnector import charger_simulator

ocpi_router = OCPIRouter()
ocpi_router.register(r'credentials', CredentialsViewSet, basename='credentials')
ocpi_router.register(r'tokens', TokenViewSet)
ocpi_router.register(r'locations', LocationViewSet)
ocpi_router.register(r'evses', EvseViewSet)
ocpi_router.register(r'tariffs', TariffViewSet)
ocpi_router.register(r'sessions', SessionViewSet)
ocpi_router.register(r'cdrs', CdrViewSet)
ocpi_router.register(r'commands', CommandsViewSet, basename='commands')

cpo_router = CPORouter()
cpo_router.register(r'evses', CpoEvseViewSet, basename='cpo-evse')
# cpo_router.register(r'cdrs', CpoCdrViewSet)
cpo_router.register(r'session', CpoSessionViewSet, basename='session')
cpo_router.register(r'location/quick', LocationQuickViewSet, basename='quick-location')

common_router = BaseRouter()
common_router.register(r'', VersionsViewSet, basename='base')

urlpatterns = [
    path('ocpi/cpo/2.2/', include(ocpi_router.urls)),
    path('api/cpo/v1/', include(cpo_router.urls)),
    path('ocpi/', include(common_router.urls)),
    path('simulator/', include(charger_simulator.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    path('openapi', get_schema_view(
        title="OCPI Connector",
        description="OpenAPI schemas for ChargerHub.EU OCPI Connector",
        version="1.0.0"
    ), name='openapi-schema'),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
