from django.db import IntegrityError
from rest_framework import status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.cpo.serializers import TariffQuickSerializer
from ocpi22.models.tariff import Tariff


class TariffQuickViewSet(mixins.ListModelMixin,
                         mixins.UpdateModelMixin,
                         mixins.RetrieveModelMixin,
                         GenericViewSet):
    """
    This is the endpoint for updating tariffs with a simplified structure. If you need to create a more complex
    Tariff, use the OCPI Tariff endpoints. The simpler the Tariff is, the easier it will be for the consumer
    to understand and estimate the cost.

    **NOTE**: All IDs should remain constant, since they are referred to by
    many systems in the roaming network.

    """
    queryset = Tariff.objects.all().order_by('created')
    serializer_class = TariffQuickSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'uid'

    def put(self, request, uid=None, partial=None):
        try:
            uid = uid or request.data.get('id')
            tariff = Tariff.get_if_exists(uid=uid)
            serializer = TariffQuickSerializer(data=request.data, instance=tariff, partial=partial)
            if serializer.is_valid():
                serializer.save()
                http_status = status.HTTP_200_OK if tariff else status.HTTP_201_CREATED
                return Response(serializer.data, status=http_status)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            return Response({'status_message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, uid=None):
        return self.put(request, uid, partial=True)

    @action(methods=['GET', 'PATCH', 'PUT'], detail=False,
            url_path='(?P<uid>[^/.]+)')
    def by_id(self, request, uid) -> Response:
        try:
            our_country_code, our_party_id = Tariff.get_owner_identity().split('*')

            tariff = get_object_or_404(Tariff, uid=uid,
                                       country_code=our_country_code,
                                       party_id=our_party_id)

            if request.method == 'GET':
                serializer = TariffQuickSerializer(tariff, context={'request': request})
                return Response(serializer.data)

            partial = bool(request.method == 'PATCH')
            serializer = TariffQuickSerializer(tariff, data=request.data, partial=partial,
                                               context={'request': request})
            if serializer.is_valid():
                serializer.save()
                # Todo: PUT fails if UID is different, require UID to be same
                serializer = TariffQuickSerializer(Tariff.objects.get(uid=uid))
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except IntegrityError as e:
            return Response({'status_message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)
