from django.db import IntegrityError
from django.forms import model_to_dict
from rest_framework import status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.serializers import SolidTariffSerializer
from ocpi22.cpo.services import SolidTariffService
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import Tariff, SolidTariff
from ocpiconnector.exceptions import MspNotFoundError
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from ocpiconnector.party import Party


class SolidTariffViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
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

    queryset = SolidTariff.objects.filter(archived=False).order_by("external_id")
    serializer_class = SolidTariffSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "external_id"
    service = SolidTariffService()

    def list(self, request, *args, **kwargs):
        serializer = SolidTariffSerializer(
            self.service.get_all_latest_solid_tariffs(), many=True
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(
        self, request, external_id=None, country_code=None, party_id=None
    ) -> Response:
        try:
            data = request.data
            data = data.get(
                "data", data
            )  # Is the actual data on the top level or one level lower?
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            serializer = SolidTariffSerializer(
                data=data,
                context={
                    "request": request,
                    "party": Party(country_code, party_id),
                },
            )
            if serializer.is_valid():
                saved_data_dict = serializer.save(ocpi_master=our_role)
                if saved_data_dict["created"]:
                    saved_data_dict["tariff"].send_updates()
                http_status = (
                    status.HTTP_200_OK
                    if saved_data_dict["solid_tariff"]
                    else status.HTTP_201_CREATED
                )
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            saved_data_dict["solid_tariff"],
                            exclude=["id", "operator", "archived"],
                        )
                    ),
                    status=http_status,
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except (IntegrityError, MspNotFoundError) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    def put(
        self, request, external_id=None, partial=None, country_code=None, party_id=None
    ) -> Response:
        try:
            data = request.data
            data = data.get(
                "data", data
            )  # Is the actual data on the top level or one level lower?
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            serializer = SolidTariffSerializer(
                data=data,
                context={
                    "request": request,
                    "party": Party(country_code, party_id),
                },
            )

            if serializer.is_valid():
                saved_data_dict = serializer.save(ocpi_master=our_role)
                if saved_data_dict["created"]:
                    saved_data_dict["tariff"].send_updates()
                http_status = (
                    status.HTTP_200_OK
                    if saved_data_dict["tariff"]
                    else status.HTTP_201_CREATED
                )
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            saved_data_dict["solid_tariff"],
                            exclude=["id", "operator", "archived"],
                        )
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
        methods=["GET", "PUT"],
        detail=False,
        url_path="(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<external_id>[^/.]+)",
    )
    def get_or_update_by_msp_id_and_external_id(
        self, request, external_id, country_code, party_id
    ) -> Response:
        try:
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            msp = Party.from_str(f"{country_code}*{party_id}").get_role_if_exists()
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

            serializer = SolidTariffSerializer(
                solid_tariff,
                data=request.data,
                partial=False,
                context={"request": request},
            )
            if serializer.is_valid():
                tariff, solid_tariff = serializer.save(ocpi_master=our_role)
                serializer = SolidTariffSerializer(
                    SolidTariff.objects.get(
                        external_id=external_id, archived=False, msp=msp
                    )
                )
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            solid_tariff, exclude=["id", "operator", "archived"]
                        )
                    ),
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
        methods=["GET", "PUT"],
        detail=False,
        url_path="(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)",
    )
    def get_or_update_by_msp_id(self, request, country_code, party_id):
        return self.get_or_update_by_msp_id_and_external_id(
            request, None, country_code, party_id
        )

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    def get_response_data(self, data: dict):
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
