from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny

from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import TariffFactory
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
            "price_flat": 0.56,
            "parking_price_per_min": 0.54,
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
        "price_per_kwh": "0.703",
        "parking_price_per_min": "0.54",
        "parking_grace_period": 100,
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "vat_percentage": "20.0",
    }


@pytest.fixture
def smp1_update_response():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": "0.703",
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "parking_price_per_min": "0.54",
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_create_response_no_msp():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": "0.69",
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "parking_price_per_min": "0.54",
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
    }


class TestSolidTariffs:
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariffs_with_all_valid_records_returns_status_code_200(
        self,
        client,
        smp1_solid_tariff_with_all_records,
        msp_de_ice,
        smp1_solid_tariff_response_with_all_records,
        operator_fi_cpo,
    ):
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_solid_tariff_with_all_records)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_solid_tariff_response_with_all_records

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariffs_by_resending_same_request_twice_creates_single_record_in_database(
        self,
        client,
        smp1_solid_tariff_with_all_records,
        msp_de_ice,
        smp1_solid_tariff_response_with_all_records,
        operator_fi_cpo,
    ):
        SolidTariff.objects.all().delete()
        url = reverse("solid-tariff-list")

        client.post(url, smp1_solid_tariff_with_all_records)
        client.post(url, smp1_solid_tariff_with_all_records)

        assert SolidTariff.objects.all().count() == 1

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariffs_with_minimal_records_returns_status_code_200(
        self,
        client,
        smp1_solid_tariff_minimal_records,
        msp_de_ice,
        smp1_solid_tariff_response_with_minimal_records,
    ):
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_solid_tariff_minimal_records)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_solid_tariff_response_with_minimal_records

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariffs_with_zero_pricing_returns_status_code_200(
        self,
        client,
        smp1_solid_tariff_zero_pricing,
        msp_de_ice,
        smp1_solid_tariff_response_with_zero_pricing,
    ):
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_solid_tariff_zero_pricing)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_solid_tariff_response_with_zero_pricing

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariff_with_minus_pricing_returns_status_code_400(
        self,
        client,
        smp1_solid_tariff_minus_pricing,
        msp_de_ice,
        smp1_solid_tariff_response_with_minus_pricing,
    ):
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_solid_tariff_minus_pricing)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == smp1_solid_tariff_response_with_minus_pricing

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_get_solid_tariffs_returns_expected_data_records(
        self,
        client,
        smp1_tariff,
        msp_de_ice,
        smp1_get_response,
        solid_tariff_smp1_msp1_data,
    ):
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        url = reverse("solid-tariff-list")
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_get_response

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_get_solid_tariff_with_invalid_msp_returns_status_code_400(
        self,
        client,
        smp1_tariff_no_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
    ):
        invalid_country_code = "ZM"
        invalid_party_id = "SPP"
        url = (
            f'{reverse("solid-tariff-list")}{invalid_country_code}/{invalid_party_id}/'
        )
        response = client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "status_message": f"No MSP found for {invalid_country_code}*{invalid_party_id}"
        }

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_get_solid_tariff_with_invalid_msp_with_external_id_returns_status_code_400(
        self,
        client,
        smp1_tariff_no_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
    ):
        invalid_country_code = "ZM"
        invalid_party_id = "SPP"
        url = (
            f'{reverse("solid-tariff-list")}{invalid_country_code}/{invalid_party_id}/'
        )
        response = client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "status_message": f"No MSP found for {invalid_country_code}*{invalid_party_id}"
        }

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_put_solid_tariff_with_all_valid_records_returns_status_code_200(
        self,
        client,
        smp1_update_tariff_data,
        solid_tariff_smp1_msp1_data,
        msp_de_ice,
        smp1_update_response,
    ):
        SolidTariff.objects.all().delete()
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_update_tariff_data)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_update_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_update_tariff_data["external_id"]
            ).count()
            == 2
        )

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_put_solid_tariff_with_minimal_records_returns_status_code_200(
        self,
        client,
        smp1_msp1_solid_tariff_with_all_records,
        smp1_solid_tariff_minimal_records,
        msp_de_ice,
        smp1_solid_tariff_response_with_minimal_records,
    ):
        SolidTariff.objects.create(**smp1_msp1_solid_tariff_with_all_records)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_solid_tariff_minimal_records)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_solid_tariff_response_with_minimal_records
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_msp1_solid_tariff_with_all_records["external_id"]
            ).count()
            == 2
        )

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_put_solid_tariff_with_zero_pricing_returns_status_code_200(
        self,
        client,
        smp1_solid_tariff_zero_pricing,
        msp_de_ice,
        smp1_msp1_solid_tariff_with_all_records,
        smp1_solid_tariff_response_with_zero_pricing,
    ):
        SolidTariff.objects.create(**smp1_msp1_solid_tariff_with_all_records)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_solid_tariff_zero_pricing)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_solid_tariff_response_with_zero_pricing
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_solid_tariff_zero_pricing["external_id"]
            ).count()
            == 2
        )

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_put_solid_tariff_with_minus_pricing_returns_status_code_400(
        self,
        client,
        smp1_solid_tariff_minus_pricing,
        msp_de_ice,
        smp1_msp1_solid_tariff_with_all_records,
        smp1_solid_tariff_response_with_minus_pricing,
    ):
        SolidTariff.objects.create(**smp1_msp1_solid_tariff_with_all_records)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_solid_tariff_minus_pricing)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == smp1_solid_tariff_response_with_minus_pricing

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_post_solid_tariff_with_no_msp_returns_status_code_200(
        self,
        client,
        smp1_tariff_no_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
        smp1_create_response_no_msp,
    ):
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff_no_msp)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_create_response_no_msp

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_put_solid_tariff_no_msp_returns_status_code_200(
        self,
        client,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp1_update_data,
        smp1_update_tariff_without_msp_response,
        smp1_update_tariff_no_msp,
        msp_de_ice,
        tariff_smp1,
    ):
        del solid_tariff_smp1_msp1_data["msp"]
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_update_tariff_no_msp)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_update_tariff_without_msp_response
        assert (
            SolidTariff.objects.filter(
                external_id=smp1_update_tariff_no_msp["external_id"]
            ).count()
            == 2
        )

    @pytest.mark.parametrize(
        "sd_type,expected_price",
        [("ENERGY", 0.23), ("TIME", 0.34), ("PARKING_TIME", 0.45), ("FLAT", 0.56)],
    )
    def test_get_type(self, sd_type, expected_price):
        sd = SolidTariff(
            external_id="SMP1",
            currency="EUR",
            price_per_kwh=0.23,
            price_per_min=0.34,
            price_flat=0.56,
            parking_price_per_min=0.45,
            parking_grace_period=0.23,
            vat_percentage=20,
        )

        assert sd.get_type(sd_type) == expected_price

    @pytest.fixture()
    def solid_tariff_smp1_msp1(self, solid_tariff_smp1_msp1_data):
        return SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

    @pytest.mark.django_db
    def test_solid_tariff_save_raises_validation_error_when_solid_tariff_pk_exists(
        self, solid_tariff_smp1_msp1_data, solid_tariff_smp1_msp1
    ):
        with pytest.raises(
            ValidationError,
            match="SolidTariff instances cannot be modified after creation.",
        ):
            solid_tariff_smp1_msp1.currency = "LKR"
            solid_tariff_smp1_msp1.save()

    @pytest.mark.django_db
    def test_solid_tariff_delete_raises_validation_error_when_immutable(
        self, solid_tariff_smp1_msp1_data, solid_tariff_smp1_msp1
    ):
        with pytest.raises(
            ValidationError, match="SolidTariff instances cannot be deleted"
        ):
            solid_tariff_smp1_msp1.delete()
