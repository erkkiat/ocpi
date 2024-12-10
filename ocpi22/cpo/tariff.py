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
from ocpiconnector.exceptions import (
    MspNotFoundError,
    SolidTariffAlreadyExistsError,
    PriceNotFoundError,
)
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
    lookup_field = "uid"

    def create(self, request, uid=None, country_code=None, party_id=None) -> Response:
        try:
            data = request.data
            data = data.get(
                "data", data
            )  # Is the actual data on the top level or one level lower?
            uid = uid or request.data.get("id")
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            msps = [
                self.get_role_or_raise(msp) for msp in set(request.data.get("msps", []))
            ]

            existing_solid_tariffs = SolidTariff.objects.filter(
                external_id__iexact=uid, operator=our_role, archived=False, msp__in=msps
            )
            if existing_solid_tariffs.exists():
                msps_with_sd = existing_solid_tariffs.all()
                raise SolidTariffAlreadyExistsError(
                    f"SolidTariff with id: {uid}, msps: {[sd.msp.party_str() for sd in msps_with_sd]} "
                    f"already exists. Please use PUT/PATCH methods."
                )

            serializer = SolidTariffSerializer(
                data=data,
                context={"request": request, "party": Party(country_code, party_id)},
            )
            if serializer.is_valid():
                tariffs, solid_tariffs = serializer.save(ocpi_master=our_role)
                for tariff in tariffs:
                    tariff.send_updates()
                http_status = status.HTTP_200_OK if tariffs else status.HTTP_201_CREATED
                return Response(
                    self.get_response_data(
                        [
                            model_to_dict(
                                solid_tariff, exclude=["id", "operator", "archived"]
                            )
                            for solid_tariff in solid_tariffs
                        ]
                    ),
                    status=http_status,
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except (IntegrityError, SolidTariffAlreadyExistsError) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

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
            serializer = SolidTariffSerializer(
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

    @action(
        methods=["GET", "PATCH", "PUT"],
        detail=False,
        url_path="(?P<uid>[^/.]+)/(?P<msp_id>[^/.]+)",
    )
    def by_id(self, request, uid, msp_id) -> Response:
        try:
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            msp = Party.from_str(msp_id).get_role_if_exists()
            if uid is None:
                solid_tariff = SolidTariff.objects.get(
                    external_id__isnull=True,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                )
            else:
                solid_tariff = SolidTariff.objects.get(
                    external_id__iexact=uid,
                    msp_id=msp.id,
                    archived=False,
                    operator=our_role,
                )

            assert request.data.get("uid") in (
                uid,
                None,
            ), "Different UID in request and URL"

            request.data["msps"] = [msp]

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
                context={"request": request, "uid": uid, "msp": msp},
            )
            if serializer.is_valid():
                tariff, solid_tariff = serializer.save(ocpi_master=our_role)
                serializer = SolidTariffSerializer(
                    SolidTariff.objects.get(external_id=uid, archived=False, msp=msp)
                )
                return Response(
                    self.get_response_data(
                        [
                            model_to_dict(
                                solid_tariff, exclude=["id", "operator", "archived"]
                            )
                        ]
                    ),
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except (
            IntegrityError,
            AssertionError,
            # Tariff.DoesNotExist,
            # SolidTariff.DoesNotExist,
            PriceNotFoundError,
        ) as e:
            return Response(
                {"status_message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        methods=["GET", "PATCH", "PUT"],
        detail=False,
        url_path="(?P<msp_id>[^/.]+)",
    )
    def by_msp_id(self, request, msp_id):
        return self.by_id(request, None, msp_id)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    def get_response_data(self, data_list: list):
        for data in data_list:
            msp = data["msp"]
            data["msp"] = CredentialsRole.objects.get(id=msp).party_str()

            external_id = data["external_id"]
            del data["external_id"]
            data["id"] = external_id

        return data_list

    def get_role_or_raise(cls, msp):
        party = Party.from_str(msp)
        role = party.get_role_if_exists()
        if not role:
            raise MspNotFoundError(f"No MSP found for {msp}")
        return role
