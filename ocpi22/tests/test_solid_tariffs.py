from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny

from ocpi22.models.tariff import SolidTariff
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


@pytest.fixture
def smp1_create_response():
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
def smp1_updated_tariff_no_msp_response():
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
def smp1_patch_response_no_msp():
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


@pytest.fixture
def smp1_patch_response():
    return {
        "external_id": "SMP1",
        "currency": "USD",
        "price_per_kwh": 0.69,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


class TestSolidTariffs:
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_create_solid_tariff(
        self, client, smp1_tariff, msp_de_ice, smp1_create_response
    ):
        get_our_credentialsrole.cache_clear()
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_create_response

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_update_solid_tariff(
        self,
        mock_get_our_credentialsrole,
        client,
        smp1_tariff,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp1_updated_data,
        smp1_updated_tariff,
        msp_de_ice,
        tariff_smp1_msp_de_ice,
        smp1_update_response,
    ):
        get_our_credentialsrole.cache_clear()
        mock_get_our_credentialsrole.return_value = msp_de_ice
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_updated_tariff)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_update_response

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_patch_solid_tariff(
        self,
        mock_get_our_credentialsrole,
        client,
        smp1_tariff,
        smp1_patch_tariff_payload,
        msp_de_ice,
        tariff_smp1_msp_de_ice,
        solid_tariff_smp1_msp1_data,
        smp1_patch_response,
    ):
        get_our_credentialsrole.cache_clear()
        mock_get_our_credentialsrole.return_value = msp_de_ice
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        patch_url = f"{reverse('solid-tariff-list')}{msp_de_ice.country_code}/{msp_de_ice.party_id}/{smp1_tariff['external_id']}/"
        response = client.patch(patch_url, smp1_patch_tariff_payload)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_patch_response

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_create_solid_tariff_with_no_msp(
        self,
        client,
        smp1_tariff_no_msp,
        msp_de_ice,
        msp_de_icd,
        operator_fi_cpo,
        smp1_patch_response_no_msp,
    ):
        get_our_credentialsrole.cache_clear()
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff_no_msp)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_patch_response_no_msp

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_update_solid_tariff_no_msp(
        self,
        client,
        smp1_tariff,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp1_updated_data,
        smp1_updated_tariff_no_msp_response,
        smp1_updated_tariff_no_msp,
        msp_de_ice,
        tariff_smp1,
    ):
        get_our_credentialsrole.cache_clear()
        del solid_tariff_smp1_msp1_data["msp"]
        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_updated_tariff_no_msp)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == smp1_updated_tariff_no_msp_response
