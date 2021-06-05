from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from ocpi22.api import OCPIRouter, TokenViewSet, LocationViewSet, TariffViewSet, EvseViewSet, SessionViewSet, CdrViewSet
from ocpi22.cpo_api import CPORouter, \
    CpoEvseViewSet, \
    SessionViewSet as CpoSessionViewSet
    # CdrViewSet as CpoCdrViewSet

ocpi_router = OCPIRouter()
ocpi_router.register(r'tokens', TokenViewSet)
ocpi_router.register(r'locations', LocationViewSet)
ocpi_router.register(r'evses', EvseViewSet)
ocpi_router.register(r'tariffs', TariffViewSet)
ocpi_router.register(r'sessions', SessionViewSet)
ocpi_router.register(r'cdrs', CdrViewSet)

cpo_router = CPORouter()
cpo_router.register(r'evses', CpoEvseViewSet, basename='cpo-evse')
# cpo_router.register(r'cdrs', CpoCdrViewSet)
cpo_router.register(r'session', CpoSessionViewSet, basename='session')

urlpatterns = [
    path('ocpi/2.2/', include(ocpi_router.urls)),
    path('api/cpo/v1/', include(cpo_router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
