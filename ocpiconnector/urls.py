from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from rest_framework import routers, serializers, viewsets

from ocpi22.models import Token


class TokenSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Token
        exclude = []


class TokenViewSet(viewsets.ModelViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all()
    serializer_class = TokenSerializer


class TokenAPIView(routers.APIRootView):
    """
    OCPI version 2.2
    ---------------

    The Charger API provides ways to access the charge point database.

    * The paged endpoint below lists all European chargers for creating a daily or weekly mirror of the database.
    * See below link for further search endpoints.
    * The list of codes used here are available at [/api/v1/common/codes/](/api/v1/common/codes/)
    """
    pass


class DocumentedRouter(routers.DefaultRouter):
    APIRootView = TokenAPIView


# Routers provide an easy way of automatically determining the URL conf.
router = DocumentedRouter()
router.register(r'tokens', TokenViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
