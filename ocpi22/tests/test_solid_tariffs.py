from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from ocpi22.models.tariff import SolidTariff
from ocpi22.tests.factories import TariffFactory
from ocpiconnector.ocpi_identities import get_our_credentialsrole


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def tariff_smp1_msp_de_ice(operator_fi_cpo):
    return TariffFactory(uid="DE*ICE*SMP1", ocpi_master=operator_fi_cpo)


@pytest.fixture
def tariff_smp1(operator_fi_cpo):
    return TariffFactory(uid="SMP1", ocpi_master=operator_fi_cpo)


@pytest.fixture
def tariff_smp1_msp_de_icd(operator_fi_cpo):
    return TariffFactory(uid="DE*ICD*SMP1", ocpi_master=operator_fi_cpo)


class TestSolidTariffs:
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_create_solid_tariff(self, client, smp1_tariff, msp_de_ice, msp2, operator):
        get_our_credentialsrole.cache_clear()
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["external_id"] == "SMP1"
        assert response.data["msp"] == "DE*ICE"
        assert response.data["price_per_kwh"] == 0.69

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
    ):
        get_our_credentialsrole.cache_clear()
        mock_get_our_credentialsrole.return_value = msp_de_ice
        created_sd = SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        assert float(created_sd.price_per_kwh) == 0.6900

        url = reverse("solid-tariff-list")
        response = client.put(url, smp1_updated_tariff)
        print(response.data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["price_per_kwh"] == smp1_updated_tariff["price_per_kwh"]

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_patch_solid_tariff(
        self,
        mock_get_our_credentialsrole,
        client,
        smp1_tariff,
        smp1_patched_tariff,
        msp_de_ice,
        tariff_smp1_msp_de_ice,
        solid_tariff_smp1_msp1_data,
    ):
        get_our_credentialsrole.cache_clear()
        mock_get_our_credentialsrole.return_value = msp_de_ice
        created_sd = SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        assert created_sd.currency == solid_tariff_smp1_msp1_data["currency"]
        patch_url = f"{reverse('solid-tariff-list')}{msp_de_ice.country_code}/{msp_de_ice.party_id}/{smp1_tariff['external_id']}/"
        response = client.patch(patch_url, smp1_patched_tariff)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["currency"] == smp1_patched_tariff["currency"]

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_create_solid_tariff_with_no_msp(
        self, client, smp1_tariff, msp_de_ice, msp2, operator
    ):
        get_our_credentialsrole.cache_clear()
        url = reverse("solid-tariff-list")
        del smp1_tariff["msp"]
        response = client.post(url, smp1_tariff)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["external_id"] == "SMP1"
        with pytest.raises(KeyError):
            assert response.data["msp"] is None
        assert response.data["price_per_kwh"] == 0.69

    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    def test_update_solid_tariff_no_msp(
        self,
        client,
        smp1_tariff,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp1_updated_data,
        smp1_updated_tariff,
        msp_de_ice,
        tariff_smp1,
    ):
        get_our_credentialsrole.cache_clear()
        del solid_tariff_smp1_msp1_data["msp"]
        created_sd = SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)

        assert float(created_sd.price_per_kwh) == 0.6900

        url = reverse("solid-tariff-list")
        del smp1_updated_tariff["msp"]
        response = client.put(url, smp1_updated_tariff)

        with pytest.raises(KeyError):
            assert response.data["msp"] is None

        assert response.status_code == status.HTTP_200_OK
        assert response.data["price_per_kwh"] == smp1_updated_tariff["price_per_kwh"]
