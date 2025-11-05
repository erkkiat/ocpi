from django.db import IntegrityError
from django.forms import model_to_dict
from rest_framework import status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.cpo.serializers import SolidTariffSerializer
from ocpi22.cpo.services import SolidTariffService
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import Tariff, SolidTariff
from ocpi22.ocpi.util import (
    IsModificationAllowed,
    HasSolidTariffDeletePermission,
)
from ocpiconnector.exceptions import MspNotFoundError
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from ocpiconnector.party import Party


class SolidTariffViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    """
    This is the endpoint for updating tariffs with a simplified structure. If you need to create a more complex
    Tariff, use the OCPI Tariff endpoints. The simpler the Tariff is, the easier it will be for the consumer
    to understand and estimate the cost.

    **NOTE**: All IDs should remain constant, since they are referred to by
    many systems in the roaming network.

    """

    queryset = SolidTariff.objects.all().order_by("external_id")
    serializer_class = SolidTariffSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "external_id"
    service = SolidTariffService()
    permission_classes = [
        IsAuthenticated,
        IsModificationAllowed,
        HasSolidTariffDeletePermission,
    ]

    def list(self, request, *args, **kwargs):
        serializer = SolidTariffSerializer(
            self.service.get_all_latest_solid_tariffs(), many=True
        )
        data = serializer.data
        for item in data:
            if "ocpi_tariff" in item and item["ocpi_tariff"]:
                item["ocpi_tariff"] = (
                    item["ocpi_tariff"].uid
                    if hasattr(item["ocpi_tariff"], "uid")
                    else item["ocpi_tariff"]
                )
        return Response(data, status=status.HTTP_200_OK)

    def put(
        self, request, external_id=None, country_code=None, party_id=None
    ) -> Response:
        try:
            data = request.data
            data = data.get("data", data)
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            serializer = SolidTariffSerializer(
                data=data,
                context={
                    "request": request,
                    "party": Party(country_code, party_id),
                },
            )
            if serializer.is_valid():
                validated_data = serializer.validated_data
                validated_data["ocpi_master"] = our_role
                solid_tariff = self.service.create(validated_data)
                http_status = (
                    status.HTTP_200_OK if solid_tariff else status.HTTP_201_CREATED
                )
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            solid_tariff,
                            exclude=["id", "operator"],
                        ),
                        solid_tariff.ocpi_tariff,
                    ),
                    status=http_status,
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except (IntegrityError, MspNotFoundError) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        methods=["GET"],
        detail=False,
        url_path="(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<external_id>[^/.]+)",
    )
    def get_by_msp_id_and_external_id(
        self, request, external_id, country_code, party_id
    ) -> Response:
        try:
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            msp = Party(country_code, party_id).get_role_if_exists()
            if msp is None:
                raise MspNotFoundError(f"No MSP found for {country_code}*{party_id}")
            if external_id is None:
                solid_tariff = SolidTariff.objects.filter(
                    external_id__isnull=True,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                ).latest("created_at")
            else:
                solid_tariff = SolidTariff.objects.filter(
                    external_id__iexact=external_id,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                ).latest("created_at")

            assert request.data.get("external_id") in (
                external_id,
                None,
            ), "Different external_id in request and URL"

            if request.method == "GET":
                serializer = SolidTariffSerializer(
                    solid_tariff, context={"request": request}
                )
                return Response(serializer.data)

        except (
            IntegrityError,
            AssertionError,
            Tariff.DoesNotExist,
            SolidTariff.DoesNotExist,
            MspNotFoundError,
        ) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        methods=["GET"],
        detail=False,
        url_path="(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)",
    )
    def get_by_msp_id(self, request, country_code, party_id):
        return self.get_by_msp_id_and_external_id(request, None, country_code, party_id)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a SolidTariff by external_id.
        This overrides the default retrieve behavior to properly handle SolidTariff lookups.
        """
        external_id = kwargs.get(self.lookup_field)

        solid_tariff = SolidTariffRepository().get_latest_with_external_id(external_id)
        if solid_tariff:
            serializer = self.get_serializer(solid_tariff)
            return Response(serializer.data)
        return Response(
            {"status_message": f"No tariff found with external_id: {external_id}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    def get_response_data(self, data: dict, tariff: Tariff) -> dict:
        data["ocpi_tariff"] = tariff.uid
        msp = data["msp"]
        if not msp:
            del data["msp"]
            return data
        msp_db = CredentialsRole.objects.get_if_exists(id=msp)
        data["msp"] = msp_db.party_str() if msp_db else ""
        return data

    def get_msp(cls, msp) -> CredentialsRole | None:
        if not msp:
            return
        party = Party.from_str(msp)
        role = party.get_role_if_exists()
        if not role:
            raise MspNotFoundError(f"No MSP found for {msp}")
        return role
