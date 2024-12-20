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

    def create(
        self, request, external_id=None, country_code=None, party_id=None
    ) -> Response:
        try:
            data = request.data
            data = data.get(
                "data", data
            )  # Is the actual data on the top level or one level lower?
            external_id = external_id or request.data.get("external_id")
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            msp = self.get_msp(request.data.get("msp"))

            existing_solid_tariff = SolidTariff.objects.filter(
                external_id__iexact=external_id,
                operator=our_role,
                archived=False,
                msp=msp,
            )
            if existing_solid_tariff.exists():
                serializer = SolidTariffSerializer(
                    data=data,
                    instance=existing_solid_tariff.first(),
                    partial=False,
                    context={
                        "request": request,
                        "party": Party(country_code, party_id),
                    },
                )
            else:
                serializer = SolidTariffSerializer(
                    data=data,
                    context={
                        "request": request,
                        "party": Party(country_code, party_id),
                    },
                )
            if serializer.is_valid():
                tariff, solid_tariff = serializer.save(ocpi_master=our_role)
                tariff.send_updates()
                http_status = (
                    status.HTTP_200_OK if solid_tariff else status.HTTP_201_CREATED
                )
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            solid_tariff, exclude=["id", "operator", "archived"]
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
            external_id = external_id or request.data.get("external_id")
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            msp = self.get_msp(request.data.get("msp"))

            existing_solid_tariff = SolidTariff.objects.filter(
                external_id__iexact=external_id,
                operator=our_role,
                archived=False,
                msp=msp,
            )

            if not existing_solid_tariff:
                serializer = SolidTariffSerializer(
                    data=data,
                    context={
                        "request": request,
                        "party": Party(country_code, party_id),
                    },
                )
            else:
                serializer = SolidTariffSerializer(
                    data=data,
                    instance=existing_solid_tariff.first(),
                    partial=partial,
                    context={
                        "request": request,
                        "party": Party(country_code, party_id),
                    },
                )
            if serializer.is_valid():
                tariff, solid_tariff = serializer.save(ocpi_master=our_role)
                tariff.send_updates()
                http_status = status.HTTP_200_OK if tariff else status.HTTP_201_CREATED
                return Response(
                    self.get_response_data(
                        model_to_dict(
                            solid_tariff, exclude=["id", "operator", "archived"]
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

    def patch(self, request, external_id=None):
        return self.put(request, external_id, partial=True)

    @action(
        methods=["GET", "PATCH", "PUT"],
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
                solid_tariff = SolidTariff.objects.get(
                    external_id__isnull=True,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                )
            else:
                solid_tariff = SolidTariff.objects.get(
                    external_id__iexact=external_id,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                )

            assert request.data.get("external_id") in (
                external_id,
                None,
            ), "Different external_id in request and URL"

            if request.method == "GET":
                serializer = SolidTariffSerializer(
                    solid_tariff, context={"request": request}
                )
                return Response(serializer.data)

            partial = bool(request.method == "PATCH")
            serializer = SolidTariffSerializer(
                solid_tariff,
                data=request.data,
                partial=partial,
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
        ) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        methods=["GET", "PATCH", "PUT"],
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
        data["msp"] = CredentialsRole.objects.get(id=msp).party_str()
        return data

    def get_msp(cls, msp) -> CredentialsRole | None:
        if not msp:
            return
        party = Party.from_str(msp)
        role = party.get_role_if_exists()
        if not role:
            raise MspNotFoundError(f"No MSP found for {msp}")
        return role
