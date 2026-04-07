import pytest
from rest_framework.exceptions import ValidationError

from ocpi22.locations.services import LocationService
from ocpi22.models.location import Location
from ocpi22.tests.factories import (
    LocationFactory,
    CredentialsFactory,
    TariffFactory,
    SolidTariffFactory,
)


@pytest.fixture
def location_service():
    service = LocationService()
    return service


class TestLocationServices:
    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_everything_when_no_credentials_provided(
        self,
    ):
        tampere = LocationFactory(uid="TAMPERE")
        joensu = LocationFactory(uid="JOENSU")
        queryset = Location.objects.all()
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            None, queryset
        )
        assert list(filtered_queryset) == [tampere, joensu]

    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_allowed_locations_only(self):
        helsinki = LocationFactory(uid="HELSINKI-ALLOWED")
        espoo = LocationFactory(uid="ESPOO-ALLOWED")
        LocationFactory(uid="VANTAA-NOT-ALLOWED")

        all_locations = Location.objects.all()
        credentials = CredentialsFactory(
            allowed_locations=["HELSINKI-ALLOWED", "ESPOO-ALLOWED"]
        )
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            credentials, all_locations
        )

        assert list(filtered_queryset) == [helsinki, espoo]

    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_all_locations_when_allowed_locations_is_empty_list(
        self,
    ):
        Location.objects.all().delete()
        LocationFactory(uid="KUOPIO")
        LocationFactory(uid="OULU")

        all_locations = Location.objects.all()
        credentials = CredentialsFactory(allowed_locations=[])
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            credentials, all_locations
        )
        assert filtered_queryset == all_locations

    @pytest.mark.django_db
    def test_convert_ocpi_tariff_ids_to_solid_tariff_ids_success(
        self, location_service
    ):
        ocpi_tariff_1 = TariffFactory(uid="ocpi_tariff_1")
        ocpi_tariff_2 = TariffFactory(uid="ocpi_tariff_2")

        SolidTariffFactory(external_id="solid_tariff_1", ocpi_tariff=ocpi_tariff_1)
        SolidTariffFactory(external_id="solid_tariff_2", ocpi_tariff=ocpi_tariff_2)

        location_data = {
            "evses": [
                {"connectors": [{"tariff_ids": ["ocpi_tariff_1", "ocpi_tariff_2"]}]}
            ]
        }

        result = location_service.convert_ocpi_tariff_ids_to_solid_tariff_ids(
            location_data
        )

        assert result["evses"][0]["connectors"][0]["tariff_ids"] == [
            "solid_tariff_1",
            "solid_tariff_2",
        ]

    @pytest.mark.django_db
    def test_convert_ocpi_tariff_ids_to_solid_tariff_ids_empty_tariff_ids(
        self, location_service
    ):
        location_data = {"evses": [{"connectors": [{"tariff_ids": []}]}]}

        result = location_service.convert_ocpi_tariff_ids_to_solid_tariff_ids(
            location_data
        )

        assert result["evses"][0]["connectors"][0]["tariff_ids"] == []

    @pytest.mark.django_db
    def test_convert_ocpi_tariff_ids_to_solid_tariff_ids_solid_tariff_not_found(
        self, location_service
    ):
        TariffFactory(uid="ocpi_tariff_1")

        location_data = {"evses": [{"connectors": [{"tariff_ids": ["ocpi_tariff_1"]}]}]}

        with pytest.raises(
            ValidationError, match="SolidTariff for OCPI tariff 'ocpi_tariff_1' not found"
        ):
            location_service.convert_ocpi_tariff_ids_to_solid_tariff_ids(location_data)

    @pytest.mark.django_db
    def test_convert_ocpi_tariff_ids_to_solid_tariff_ids_multiple_evses(
        self, location_service
    ):
        ocpi_tariff_1 = TariffFactory(uid="ocpi_tariff_1")
        ocpi_tariff_2 = TariffFactory(uid="ocpi_tariff_2")

        SolidTariffFactory(external_id="solid_tariff_1", ocpi_tariff=ocpi_tariff_1)
        SolidTariffFactory(external_id="solid_tariff_2", ocpi_tariff=ocpi_tariff_2)

        location_data = {
            "evses": [
                {"connectors": [{"tariff_ids": ["ocpi_tariff_1"]}]},
                {"connectors": [{"tariff_ids": ["ocpi_tariff_2"]}]},
            ]
        }

        result = location_service.convert_ocpi_tariff_ids_to_solid_tariff_ids(
            location_data
        )

        assert result["evses"][0]["connectors"][0]["tariff_ids"] == ["solid_tariff_1"]
        assert result["evses"][1]["connectors"][0]["tariff_ids"] == ["solid_tariff_2"]

    @pytest.mark.django_db
    def test_convert_ocpi_tariff_ids_to_solid_tariff_ids_with_no_evses(
        self, location_service
    ):
        location_data = {"uid": "LOC1", "name": "Test"}

        result = location_service.convert_ocpi_tariff_ids_to_solid_tariff_ids(
            location_data
        )

        assert result == {"uid": "LOC1", "name": "Test"}
