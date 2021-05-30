from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from ocpi22.api import OCPIRouter, CPORouter, TokenViewSet, LocationViewSet, TariffViewSet, EvseViewSet, CpoEvseViewSet

# Routers provide an easy way of automatically determining the URL conf.
ocpi_router = OCPIRouter()
ocpi_router.register(r'tokens', TokenViewSet)
ocpi_router.register(r'locations', LocationViewSet)
ocpi_router.register(r'evses', EvseViewSet)
ocpi_router.register(r'tariffs', TariffViewSet)

cpo_router = CPORouter()
cpo_router.register(r'evses', CpoEvseViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(ocpi_router.urls)),
    path('api/cpo/v1/', include(cpo_router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('tokens/', tokens)
]
