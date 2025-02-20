import pytest
from django.conf import settings
import responses

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.location import Connector, Location
from ocpi22.tests.factories import LocationFactory, EvseFactory, ConnectorFactory
from ocpiconnector.ocpi_identities import get_our_party


@pytest.fixture
def connector_without_tariff():
    Location.objects.all().delete()
    location = LocationFactory(uid="location-without-tariff")
    evse = EvseFactory(location=location)

    connector = ConnectorFactory(uid="connector_without_tariff")
    evse.connectors.set([connector])
    location.evses.set([evse])

    Connector.objects.filter(uid="connector_without_tariff").first().tariff_ids.set([])

    return connector


class TestHubjectApi:
    @pytest.mark.django_db
    @responses.activate
    def test_evse_full_load_api_returns_200_OK(
        self, client, hubject_successful_response, helsinki_location
    ):
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/FI*CPO/data-records",
            json=hubject_successful_response,
            status=200,
        )

        url = "/api/hubject/2.3/evses/full-load/"
        response = client.post(url)
        assert response.status_code == 200
        assert response.json() == hubject_successful_response

    @pytest.mark.django_db
    def test_evse_full_load_api_returns_no_evse_records_found(self, client):
        url = "/api/hubject/2.3/evses/full-load/"
        response = client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "No EvseDataRecords found for operator FI*CPO",
        }

    @pytest.mark.django_db
    def test_evse_full_load_api_returns_no_tariffs_found_for_evses(
        self, client, connector_without_tariff
    ):
        url = "/api/hubject/2.3/evses/full-load/"
        response = client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "No tariff were found for one or more of the evses.",
        }

    @responses.activate
    @pytest.mark.django_db
    def test_start_pricing_products_full_load_returns_200_OK(
        self, client, hubject_successful_response, smp1_solid_tariff
    ):
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/FI*CPO/pricing-products",
            json=hubject_successful_response,
            status=200,
        )

        url = "/api/hubject/2.3/pricing-products/full-load/"
        response = client.post(url)
        assert response.status_code == 200
        assert response.json() == hubject_successful_response

    @pytest.mark.django_db
    def test_start_pricing_products_full_load_returns_no_solid_tariffs_found(
        self, client, hubject_successful_response
    ):
        party = get_our_party(OcpiRolesEnum.CPO)

        url = "/api/hubject/2.3/pricing-products/full-load/"
        response = client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": f"No Solid Tariffs found for {str(party)}",
        }
