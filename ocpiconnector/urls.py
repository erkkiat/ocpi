from django.conf.urls import include
from django.contrib import admin
from django.urls import path
from rest_framework.schemas import get_schema_view

from ocpi22.api import OCPIRouter, TokenViewSet, TariffViewSet, SessionViewSet, CdrViewSet, CredentialsViewSet, \
    RootRouter, ClientInfoViewSet
from ocpi22.commands import CommandsViewSet
from ocpi22.cpo_api import CPORouter, \
    CpoEvseViewSet, \
    SessionViewSet as CpoSessionViewSet, LocationQuickViewSet

from ocpi22.location import LocationViewSet
from ocpi22.models.credentials import new_connection
from ocpi22.versions import VersionsViewSet, BaseRouter
from ocpiconnector import charger_simulator

ocpi_router = OCPIRouter()
ocpi_router.register(r'credentials', CredentialsViewSet, basename='credentials')
ocpi_router.register(r'clientinfo', ClientInfoViewSet, basename='clientinfo')
ocpi_router.register(r'tokens', TokenViewSet)
ocpi_router.register(r'locations', LocationViewSet)
ocpi_router.register(r'tariffs', TariffViewSet)
ocpi_router.register(r'sessions', SessionViewSet)
ocpi_router.register(r'cdrs', CdrViewSet)
ocpi_router.register(r'commands', CommandsViewSet, basename='commands')

cpo_router = CPORouter()
cpo_router.register(r'evses', CpoEvseViewSet, basename='cpo-evse')
# cpo_router.register(r'cdrs', CpoCdrViewSet)
cpo_router.register(r'session', CpoSessionViewSet, basename='session')
cpo_router.register(r'location/quick', LocationQuickViewSet, basename='quick-location')

root_router = RootRouter()

common_router = BaseRouter()
common_router.register(r'', VersionsViewSet, basename='base')

urlpatterns = [
    path('', include(root_router.urls), name='root-view'),
    path('ocpi/cpo/2.2/', include(ocpi_router.urls), name='ocpi-22-root'),
    path('api/cpo/v1/', include(cpo_router.urls), name='cpo-interface'),
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
]
