import json
from unittest.mock import patch

from datetime import datetime

import pytest
from django.contrib.auth.models import Permission
from django.core.serializers import serialize
import time_machine
from django.urls import reverse
from rest_framework import status

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff, Tariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import TariffFactory, SolidTariffFactory
from ocpiconnector.ocpi_identities import get_our_credentialsrole


@pytest.fixture
def tariff_smp1_msp_de_ice(operator_fi_cpo):
    return TariffFactory(uid="DE*ICE*SMP1", ocpi_master=operator_fi_cpo)


@pytest.fixture
def tariff_smp1(operator_fi_cpo):
    return TariffFactory(uid="SMP1", ocpi_master=operator_fi_cpo)


@pytest.fixture
def tariff_smp1_msp_de_icd(operator_fi_cpo):
    return TariffFactory(uid="DE*ICD*SMP1", ocpi_master=operator_fi_cpo)


@pytest.fixture(autouse=True)
def clear_cache():
    get_our_credentialsrole.cache_clear()
    get_credentialsrole.cache_clear()


@pytest.fixture
def solid_tariff_smp1_msp1(msp_de_ice, operator_fi_cpo):
    return SolidTariffFactory(
        external_id="SMP1",
        currency="EUR",
        price_per_kwh=0.690,
        price_per_min=0.42,
        price_per_hr=0.6,
        price_flat=0.56,
        parking_price_per_min=0.54,
        parking_price_per_hr=0.8,
        parking_grace_period=100,
        vat_percentage=20.0,
        last_updated=datetime(2024, 9, 22, 12, 30, 30, 0),
        msp=msp_de_ice,
        operator=operator_fi_cpo,
    )


@pytest.fixture
def solid_tariff_smp1_without_msp():
    return SolidTariffFactory(
        external_id="SMP1",
        currency="EUR",
        price_per_kwh=0.690,
        price_per_min=0.42,
        price_per_hr=0.6,
        price_flat=0.56,
        parking_price_per_min=0.54,
        parking_price_per_hr=0.8,
        parking_grace_period=100,
        vat_percentage=20.0,
        last_updated=datetime(2024, 9, 22, 12, 30, 30, 0),
    )


@pytest.fixture
def smp1_create_response_all_records():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": "0.69",
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "parking_price_per_min": "0.54",
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_get_response():
    return [
        {
            "external_id": "SMP1",
            "currency": "EUR",
            "price_per_kwh": 0.69,
            "price_per_min": 0.42,
            "price_per_hr": 0.6,
            "price_flat": 0.56,
            "parking_price_per_min": 0.54,
            "parking_price_per_hr": 0.8,
            "parking_grace_period": 100,
            "vat_percentage": 20.0,
            "msp": "DE*ICE",
        }
    ]


@pytest.fixture
def smp1_update_tariff_without_msp_response():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "parking_price_per_min": 0.54,
        "parking_price_per_hr": 0.8,
        "parking_grace_period": 100,
        "price_per_min": 0.42,
        "price_per_hr": 0.6,
        "price_flat": 0.56,
        "vat_percentage": "20.0",
        "last_updated": "2024-09-22T12:30:30Z",
    }


@pytest.fixture
def smp1_update_response():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_per_hr": 0.6,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_price_per_hr": 0.8,
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
        "msp": "DE*ICE",
        "last_updated": "2024-09-22T12:30:30Z",
    }


@pytest.fixture
def smp1_create_response_no_msp():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.69,
        "price_per_min": 0.42,
        "price_per_hr": 0.6,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_price_per_hr": 0.8,
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
        "last_updated": "2024-09-22T12:30:30Z",
    }


@pytest.fixture
def delete_permissions_for_super_user(super_user):
    super_user.user_permissions.set([])


@pytest.fixture
def super_user_with_delete_solid_tariff_permission(super_user):
    permission = Permission.objects.get(codename="delete_solidtariff")
    super_user.user_permissions.set([permission])


@pytest.fixture(scope="class", autouse=True)
def freeze_time():
    with time_machine.travel(datetime(2024, 9, 22, 12, 30, 30, 0), tick=False):
        yield


class TestSolidTariffs:
    @pytest.mark.parametrize(
        "method, payload, expected_status",
        [
            pytest.param(
                "get",
                None,
                status.HTTP_401_UNAUTHORIZED,
                id="unauthenticated_user_cannot_get_solid_tariff",
            ),
            pytest.param(
                "post",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_401_UNAUTHORIZED,
                id="unauthenticated_user_cannot_post_solid_tariff",
            ),
            pytest.param(
                "put",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_401_UNAUTHORIZED,
                id="unauthenticated_user_cannot_put_solid_tariff",
            ),
            pytest.param(
                "delete",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_401_UNAUTHORIZED,
                id="unauthenticated_user_cannot_delete_solid_tariff",
            ),
        ],
    )
    def test_unauthenticated_user_http_methods_on_solid_tariffs(
        self, client, method, payload, expected_status
    ):
        url = reverse("solid-tariff-list")
        response = getattr(client, method)(url, payload)
        assert response.status_code == expected_status

    def test_unauthenticated_user_cannot_delete_solid_tariff_by_external_id_returns_401_unauthorized(
        self, client
    ):
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = client.delete(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        "method, payload, expected_status",
        [
            pytest.param(
                "get",
                None,
                status.HTTP_200_OK,
                id="authenticated_user_can_get_solid_tariff",
            ),
            pytest.param(
                "post",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_405_METHOD_NOT_ALLOWED,
                id="authenticated_user_cannot_post_solid_tariff",
            ),
            pytest.param(
                "put",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_200_OK,
                id="authenticated_user_can_put_solid_tariff",
            ),
            pytest.param(
                "delete",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_403_FORBIDDEN,
                id="authenticated_user_cannot_delete_solid_tariff",
            ),
        ],
    )
    def test_authenticated_user_http_methods_on_solid_tariffs(
        self, authenticated_user_client, method, payload, expected_status
    ):
        url = reverse("solid-tariff-list")
        response = (
            getattr(authenticated_user_client, str(method))(url, payload)
            if payload
            else getattr(authenticated_user_client, str(method))(url)
        )
        assert response.status_code == expected_status

    def test_authenticated_user_cannot_delete_solid_tariff_by_external_id_403_forbidden(
        self, authenticated_user_client, smp1_solid_tariff_with_all_records_json
    ):
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = authenticated_user_client.delete(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize(
        "method, payload, expected_status",
        [
            pytest.param(
                "get", None, status.HTTP_200_OK, id="admin_user_can_get_solid_tariff"
            ),
            pytest.param(
                "post",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_405_METHOD_NOT_ALLOWED,
                id="admin_user_cannot_post_solid_tariff",
            ),
            pytest.param(
                "put",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_200_OK,
                id="admin_user_can_put_solid_tariff",
            ),
            pytest.param(
                "delete",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_403_FORBIDDEN,
                id="admin_user_cannot_delete_solid_tariff",
            ),
        ],
    )
    def test_admin_user_http_methods_on_solid_tariffs(
        self, admin_user_client, method, payload, expected_status
    ):
        url = reverse("solid-tariff-list")
        response = (
            getattr(admin_user_client, method)(url, payload)
            if payload
            else getattr(admin_user_client, method)(url)
        )
        assert response.status_code == expected_status

    def test_admin_user_cannot_delete_solid_tariff_by_external_id_403_forbidden(
        self, admin_user_client, smp1_solid_tariff_with_all_records_json
    ):
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = admin_user_client.delete(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize(
        "method, payload, expected_status",
        [
            pytest.param(
                "get", None, status.HTTP_200_OK, id="super_user_can_get_solid_tariff"
            ),
            pytest.param(
                "post",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_405_METHOD_NOT_ALLOWED,
                id="super_user_cannot_post_solid_tariff",
            ),
            pytest.param(
                "put",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_200_OK,
                id="super_user_can_put_solid_tariff",
            ),
            pytest.param(
                "delete",
                {"external_id": "SMP1", "currency": "EUR", "price_flat": 1.0},
                status.HTTP_403_FORBIDDEN,
                id="super_user_cannot_delete_solid_tariff",
            ),
        ],
    )
    def test_super_user_http_methods_on_solid_tariffs(
        self, super_user_client, method, payload, expected_status
    ):
        url = reverse("solid-tariff-list")
        response = (
            getattr(super_user_client, method)(url, payload)
            if payload
            else getattr(super_user_client, method)(url)
        )
        assert response.status_code == expected_status

    def test_super_user_cannot_delete_solid_tariff_returns_405(
        self,
        super_user_client,
        smp1_solid_tariff_with_all_records_json,
        delete_permissions_for_super_user,
        super_user,
        solid_tariff_smp1_msp1,
    ):
        permission = Permission.objects.get(codename="delete_solidtariff")
        super_user.user_permissions.set([permission])
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = super_user_client.delete(url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_super_user_cannot_delete_solid_tariff_without_delete_permission_return_403_forbidden(
        self,
        super_user_client,
        delete_permissions_for_super_user,
        solid_tariff_smp1_msp1,
    ):
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = super_user_client.delete(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_super_user_cannot_delete_solid_tariff_by_external_id_405(
        self,
        super_user_client,
        smp1_solid_tariff_with_all_records_json,
        solid_tariff_smp1_msp1,
        super_user_with_delete_solid_tariff_permission,
    ):
        url = f'{reverse("solid-tariff-list")}SMP1/'
        response = super_user_client.delete(url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @pytest.mark.django_db
    def test_put_solid_tariffs_with_all_valid_records_returns_status_code_200(
        self,
        authenticated_user_client,
        msp_de_ice,
        operator_fi_cpo,
        smp1_msp1_solid_tariff_with_all_records,
        smp1_solid_tariff_with_all_records_json,
        smp1_solid_tariff_with_all_records_response,
    ):
        url = reverse("solid-tariff-list")
        with patch(
            "ocpi22.ocpi.util.OcpiModule.post_process_after_update_or_create"
        ) as mock_send_updates:
            response = authenticated_user_client.put(
                url, smp1_solid_tariff_with_all_records_json
            )
            response_json = response.json()
            tariff = Tariff.objects.get(uid=response_json["ocpi_tariff"])
            assert (
                tariff.price() == "0,69€/kWh + 0,60€/h + 0,56€ flat + 0,80€/h parking"
            )

            assert response.status_code == status.HTTP_200_OK

            smp1_solid_tariff_with_all_records_response["ocpi_tariff"] = tariff.uid
            assert response_json == smp1_solid_tariff_with_all_records_response
            mock_send_updates.assert_called_once()

    @pytest.mark.django_db
    def test_put_solid_tariffs_by_resending_same_request_twice_creates_single_record_in_database(
        self,
        authenticated_user_client,
        smp1_solid_tariff_with_all_records_json,
        msp_de_ice,
        operator_fi_cpo,
    ):
        url = reverse("solid-tariff-list")

        authenticated_user_client.put(url, smp1_solid_tariff_with_all_records_json)
        authenticated_user_client.put(url, smp1_solid_tariff_with_all_records_json)

        assert SolidTariff.objects.all().count() == 1
        json_data = serialize("json", SolidTariff.objects.all())
        assert self.verify_saved_model_json_and_expected(
            json_data, smp1_solid_tariff_with_all_records_json
        )

    @pytest.mark.django_db
    def test_put_solid_tariffs_with_minimal_records_returns_status_code_200(
        self,
        authenticated_user_client,
        smp1_solid_tariff_minimal_records_json,
        msp_de_ice,
        smp1_solid_tariff_with_minimal_records_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_minimal_records_json
        )

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_solid_tariff_with_minimal_records_response["ocpi_tariff"] = response_json[
            "ocpi_tariff"
        ]
        assert response_json == smp1_solid_tariff_with_minimal_records_response

    @pytest.mark.django_db
    def test_put_solid_tariffs_with_zero_pricing_returns_status_code_200(
        self,
        authenticated_user_client,
        smp1_solid_tariff_zero_pricing_json,
        msp_de_ice,
        smp1_solid_tariff_with_zero_pricing_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_zero_pricing_json
        )

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_solid_tariff_with_zero_pricing_response["ocpi_tariff"] = response_json[
            "ocpi_tariff"
        ]
        assert response_json == smp1_solid_tariff_with_zero_pricing_response

    @pytest.mark.django_db
    def test_put_solid_tariffs_with_no_pricing_returns_status_code_400(
        self,
        authenticated_user_client,
        msp_de_ice,
    ):
        url = reverse("solid-tariff-list")
        payload = {
            "external_id": "SMP1",
            "currency": "EUR",
            "vat_percentage": 20.0,
            "msp": "DE*ICE",
        }
        response = authenticated_user_client.put(url, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "At least one pricing field must be provided." in str(response.json())

    @pytest.mark.django_db
    def test_put_solid_tariff_with_minus_pricing_returns_status_code_400(
        self,
        authenticated_user_client,
        smp1_solid_tariff_minus_pricing_json,
        msp_de_ice,
        smp1_solid_tariff_with_minus_pricing_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_minus_pricing_json
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == smp1_solid_tariff_with_minus_pricing_response

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "pricing_type, price",
        [
            pytest.param("price_per_kwh", "9999999.9999999", id="price_per_kwh exceeds 12 max_digits"),
            pytest.param("price_per_kwh", "0.1234567", id="price_per_kwh exceeds 6 decimal_places"),
            pytest.param("price_per_min", "0.12345678901", id="price_per_min exceeds 10 decimal_places"),
        ],
    )
    def test_put_solid_tariff_with_too_many_digits_returns_status_code_400(
        self,
        authenticated_user_client,
        msp_de_ice,
        pricing_type,
        price,
    ):
        url = reverse("solid-tariff-list")
        payload = {
            "external_id": "SMP1",
            "currency": "EUR",
            "msp": "DE*ICE",
            pricing_type: price,
        }
        response = authenticated_user_client.put(url, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert pricing_type in response.json()

    @pytest.mark.django_db
    def test_get_solid_tariffs_returns_expected_data_records(
        self, authenticated_user_client, smp1_get_response, solid_tariff_smp1_msp1
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.get(url)
        response_json = response.json()
        smp1_get_response[0]["last_updated"] = response_json[0]["last_updated"]
        smp1_get_response[0]["ocpi_tariff"] = response_json[0]["ocpi_tariff"]

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_get_response

    @pytest.mark.django_db
    def test_retrieve_solid_tariff_by_external_id_returns_expected_data(
        self, authenticated_user_client, solid_tariff_smp1_msp1
    ):
        from urllib.parse import urljoin

        url = urljoin(reverse("solid-tariff-list"), "SMP1/")
        response = authenticated_user_client.get(url)
        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        assert response_json["external_id"] == "SMP1"
        assert response_json["currency"] == "EUR"
        assert response_json["price_per_kwh"] == 0.69
        assert response_json["price_per_min"] == 0.42
        assert response_json["price_flat"] == 0.56
        assert response_json["parking_price_per_min"] == 0.54
        assert response_json["parking_grace_period"] == 100
        assert response_json["vat_percentage"] == 20.0
        assert response_json["msp"] == "DE*ICE"

    @pytest.mark.django_db
    def test_retrieve_nonexistent_solid_tariff_returns_404(
        self, authenticated_user_client
    ):
        url = f'{reverse("solid-tariff-list")}NONEXISTENT/'
        response = authenticated_user_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {
            "status_message": "No tariff found with external_id: NONEXISTENT"
        }

    @pytest.mark.django_db
    def test_get_solid_tariff_with_invalid_msp_returns_status_code_400(
        self,
        authenticated_user_client,
        solid_tariff_smp1_without_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
    ):
        invalid_country_code = "ZM"
        invalid_party_id = "SPP"
        url = (
            f'{reverse("solid-tariff-list")}{invalid_country_code}/{invalid_party_id}/'
        )
        response = authenticated_user_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "status_message": f"No MSP found for {invalid_country_code}*{invalid_party_id}"
        }

    @pytest.mark.django_db
    def test_get_solid_tariff_with_invalid_msp_with_external_id_returns_status_code_400(
        self,
        authenticated_user_client,
        solid_tariff_smp1_without_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
    ):
        invalid_country_code = "ZM"
        invalid_party_id = "SPP"
        url = (
            f'{reverse("solid-tariff-list")}{invalid_country_code}/{invalid_party_id}/'
        )
        response = authenticated_user_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "status_message": f"No MSP found for {invalid_country_code}*{invalid_party_id}"
        }

    @pytest.mark.django_db
    def test_update_solid_tariff_with_all_valid_records_create_a_new_solid_tariff(
        self,
        authenticated_user_client,
        smp1_update_solid_tariff_json,
        solid_tariff_smp1_msp1_json,
        msp_de_ice,
        smp1_update_response,
        solid_tariff_smp1_msp1,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(url, smp1_update_solid_tariff_json)

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_update_response["ocpi_tariff"] = response_json["ocpi_tariff"]
        assert response.json() == smp1_update_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_update_solid_tariff_json["external_id"]
            ).count()
            == 2
        )
        json_data = serialize(
            "json",
            (
                SolidTariff.objects.filter(
                    external_id=smp1_update_solid_tariff_json["external_id"]
                ).order_by("-created_at")
            ),
        )

        assert self.verify_saved_model_json_and_expected(
            json_data, solid_tariff_smp1_msp1
        )

    @pytest.mark.django_db
    def test_update_solid_tariff_with_minimal_records_create_a_new_solid_tariff(
        self,
        authenticated_user_client,
        smp1_solid_tariff_minimal_records_json,
        msp_de_ice,
        solid_tariff_smp1_msp1,
        smp1_solid_tariff_with_minimal_records_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_minimal_records_json
        )

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_solid_tariff_with_minimal_records_response["ocpi_tariff"] = response_json[
            "ocpi_tariff"
        ]
        assert response_json == smp1_solid_tariff_with_minimal_records_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_solid_tariff_minimal_records_json["external_id"]
            ).count()
            == 2
        )
        json_data = serialize(
            "json",
            (
                SolidTariff.objects.filter(
                    external_id=smp1_solid_tariff_minimal_records_json["external_id"]
                ).order_by("-created_at")
            ),
        )

        assert self.verify_saved_model_json_and_expected(
            json_data, smp1_solid_tariff_minimal_records_json
        )

    @pytest.mark.django_db
    def test_update_solid_tariff_with_zero_pricing_create_a_new_solid_tariff(
        self,
        authenticated_user_client,
        smp1_solid_tariff_zero_pricing_json,
        msp_de_ice,
        solid_tariff_smp1_msp1,
        smp1_solid_tariff_with_zero_pricing_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_zero_pricing_json
        )

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_solid_tariff_with_zero_pricing_response["ocpi_tariff"] = response_json[
            "ocpi_tariff"
        ]
        assert response_json == smp1_solid_tariff_with_zero_pricing_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_solid_tariff_zero_pricing_json["external_id"]
            ).count()
            == 2
        )
        json_data = serialize(
            "json",
            (
                SolidTariff.objects.filter(
                    external_id=smp1_solid_tariff_zero_pricing_json["external_id"]
                ).order_by("-created_at")
            ),
        )

        assert self.verify_saved_model_json_and_expected(
            json_data, smp1_solid_tariff_zero_pricing_json
        )

    @pytest.mark.django_db
    def test_update_solid_tariff_with_minus_pricing_returns_status_code_400(
        self,
        authenticated_user_client,
        smp1_solid_tariff_minus_pricing_json,
        msp_de_ice,
        solid_tariff_smp1_msp1,
        smp1_solid_tariff_with_minus_pricing_response,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(
            url, smp1_solid_tariff_minus_pricing_json
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == smp1_solid_tariff_with_minus_pricing_response

    @pytest.mark.django_db
    def test_post_solid_tariff_with_no_msp_returns_status_code_200(
        self,
        authenticated_user_client,
        smp1_tariff_no_msp_json,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
        smp1_create_response_no_msp,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(url, smp1_tariff_no_msp_json)

        assert response.status_code == status.HTTP_200_OK
        response_json = response.json()
        smp1_create_response_no_msp["ocpi_tariff"] = response_json["ocpi_tariff"]
        assert response_json == smp1_create_response_no_msp

    @pytest.mark.django_db
    def test_update_solid_tariff_no_msp_create_a_new_solid_tariff(
        self,
        authenticated_user_client,
        smp1_update_tariff_without_msp_response,
        smp1_update_tariff_without_msp,
        solid_tariff_smp1_without_msp,
    ):
        url = reverse("solid-tariff-list")
        response = authenticated_user_client.put(url, smp1_update_tariff_without_msp)

        response_json = response.json()

        assert response.status_code == status.HTTP_200_OK
        smp1_update_tariff_without_msp_response["ocpi_tariff"] = response_json[
            "ocpi_tariff"
        ]
        assert response_json == smp1_update_tariff_without_msp_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_update_tariff_without_msp["external_id"]
            ).count()
            == 2
        )
        json_data = serialize(
            "json",
            (
                SolidTariff.objects.filter(
                    external_id=smp1_update_tariff_without_msp["external_id"]
                ).order_by("-created_at")
            ),
        )

        assert self.verify_saved_model_json_and_expected(
            json_data, smp1_update_tariff_without_msp
        )

    @pytest.mark.parametrize(
        "sd_type,expected_price",
        [
            ("ENERGY", 0.23),
            ("TIME_MIN", 0.34),
            ("TIME_HR", 0.6),
            ("PARKING_TIME_MIN", 0.45),
            ("PARKING_TIME_HR", 0.8),
            ("FLAT", 0.56),
        ],
    )
    def test_get_type(self, sd_type, expected_price):
        sd = SolidTariff(
            external_id="SMP1",
            currency="EUR",
            price_per_kwh=0.23,
            price_per_min=0.34,
            price_per_hr=0.6,
            price_flat=0.56,
            parking_price_per_min=0.45,
            parking_price_per_hr=0.8,
            parking_grace_period=0.23,
            vat_percentage=20,
        )

        assert sd.get_type(sd_type) == expected_price

    def verify_saved_model_json_and_expected(self, json_data, expected_json):
        saved_data = json.loads(json_data)[0]["fields"]

        saved_data["price_per_kwh"] = (
            float(saved_data["price_per_kwh"])
            if saved_data["price_per_kwh"] is not None
            else None
        )
        saved_data["price_per_min"] = (
            float(saved_data["price_per_min"])
            if saved_data["price_per_min"] is not None
            else None
        )
        saved_data["price_flat"] = (
            float(saved_data["price_flat"])
            if saved_data["price_flat"] is not None
            else None
        )
        saved_data["parking_price_per_min"] = (
            float(saved_data["parking_price_per_min"])
            if saved_data["parking_price_per_min"] is not None
            else None
        )

        if saved_data["msp"] == 1:
            saved_data["msp"] = CredentialsRole.objects.get(id=1)

        return (
            saved_data == expected_json,
            f"Mismatch:\nExpected: {expected_json}\nActual: {saved_data}",
        )
