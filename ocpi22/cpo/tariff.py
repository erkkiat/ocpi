from django.db import IntegrityError
from rest_framework import status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.serializers import TariffQuickSerializer
from ocpi22.models.tariff import Tariff
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from ocpiconnector.party import Party


class TariffQuickViewSet(
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.RetrieveModelMixin,
    GenericViewSet,
):
    """
    This is the endpoint for updating tariffs with a simplified structure. If you need to create a more complex
    Tariff, use the OCPI Tariff endpoints. The simpler the Tariff is, the easier it will be for the consumer
    to understand and estimate the cost.

    **NOTE**: All IDs should remain constant, since they are referred to by
    many systems in the roaming network.

    """

    queryset = Tariff.objects.filter(archived=False).order_by("uid")
    serializer_class = TariffQuickSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "uid"

    def put(
        self, request, uid=None, partial=None, country_code=None, party_id=None
    ) -> Response:
        try:
            data = request.data
            data = data.get(
                "data", data
            )  # Is the actual data on the top level or one level lower?
            uid = uid or request.data.get("id")
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            tariff = Tariff.get_if_exists(
                uid__iexact=uid, ocpi_master=our_role, archived=False
            )
            serializer = TariffQuickSerializer(
                data=data,
                instance=tariff,
                partial=partial,
                context={"request": request, "party": Party(country_code, party_id)},
            )
            if serializer.is_valid():
                tariff = serializer.save(ocpi_master=our_role)
                tariff.send_updates()
                http_status = status.HTTP_200_OK if tariff else status.HTTP_201_CREATED
                return Response(serializer.data, status=http_status)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    def patch(self, request, uid=None):
        return self.put(request, uid, partial=True)

    @action(methods=["GET", "PATCH", "PUT"], detail=False, url_path="(?P<uid>[^/.]+)")
    def by_id(self, request, uid) -> Response:
        try:
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            tariff = Tariff.objects.get(
                uid__iexact=uid, archived=False, ocpi_master=our_role
            )

            assert request.data.get("uid") in (
                uid,
                None,
            ), "Different UID in request and URL"

            if request.method == "GET":
                serializer = TariffQuickSerializer(tariff, context={"request": request})
                return Response(serializer.data)

            partial = bool(request.method == "PATCH")
            serializer = TariffQuickSerializer(
                tariff, data=request.data, partial=partial, context={"request": request}
            )
            if serializer.is_valid():
                serializer.save(ocpi_master=our_role)
                serializer = TariffQuickSerializer(Tariff.objects.get(uid=uid))
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except (IntegrityError, AssertionError, Tariff.DoesNotExist) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)
