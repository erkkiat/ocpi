from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import HyperlinkedModelSerializerCleanedUp, OCPIViewSetMixin
from ocpi22.models import Evse


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['cpo_url', 'uid', 'status']


class EvseViewSet(mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin,
                     mixins.ListModelMixin,
                     OCPIViewSetMixin,
                     GenericViewSet):

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<evse_id>[^/.]+)', url_name='by-id-cpo')
    def evse_by_id(self, request, evse_id) -> Response:
        """
        This URL is used for sending charger status updates using the PATCH method. Status updates should be
        real time, so that the eMSPs can show the current availability to their customers.

        You can try the status update by typing a different status
        in the input box below and clicking the "PATCH" button.

        Some available options for status are:

        * AVAILABLE
        * CHARGING
        * REMOVED (this is used instead of deleting the EVSE, since there might be references to it)
        * PLANNED
        * More options are listed at [/api/cpo/v1/options/](/api/cpo/v1/options/)

        """
        evse = get_object_or_404(Evse, uid=evse_id)

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    CPO API
    ---------------

    This portal provides ways to view the information in the database, read the API documentation and
    try out sending information to the API. The OCPI API serves both the eMSP and the CPO.

    1. The CPO specific interfaces are available at [/api/v1/cpo/](/api/v1/cpo/)
    """


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
