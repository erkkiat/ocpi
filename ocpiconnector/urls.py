from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from ocpi22.api import DocumentedRouter, TokenViewSet, LocationViewSet, TariffViewSet, EvseViewSet

# Routers provide an easy way of automatically determining the URL conf.
router = DocumentedRouter()
router.register(r'tokens', TokenViewSet)
router.register(r'locations', LocationViewSet)
router.register(r'evses', EvseViewSet)
router.register(r'tariffs', TariffViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('tokens/', tokens)
]
