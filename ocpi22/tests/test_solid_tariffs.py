from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from ocpi22.models.tariff import SolidTariff
from ocpi22.tests.factories import TariffFactory


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def tariff_smp1_msp1(operator):
    return TariffFactory(uid="DE*ICE*SMP1", ocpi_master=operator)


@pytest.fixture
def tariff_smp1_msp2(operator):
    return TariffFactory(uid="DE*ICD*SMP1", ocpi_master=operator)


class TestSolidTariffs:
    @pytest.mark.skip(reason="Cached function gives trouble here")
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_create_solid_tariff(
        self, mock_get_our_credentialsrole, client, smp1_tariff, msp1, msp2, operator
    ):
        mock_get_our_credentialsrole.return_value = operator
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    @pytest.mark.skip(reason="Cached function giving trouble here")
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_update_solid_tariff(
        self,
        mock_get_our_credentialsrole,
        client,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp2_data,
        solid_tariff_smp1_msp1_updated_data,
        smp1_updated_tariff,
        msp1,
        msp2,
        operator,
        tariff_smp1_msp1,
        tariff_smp1_msp2,
    ):
        mock_get_our_credentialsrole.return_value = operator
        url = f"{reverse('solid-tariff-list')}{solid_tariff_smp1_msp1_data['external_id']}/{msp1.party_str()}/"

        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)
        SolidTariff.objects.create(**solid_tariff_smp1_msp2_data)

        response = client.put(url, smp1_updated_tariff, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["price_per_kwh"] == smp1_updated_tariff["price_per_kwh"]

    @pytest.mark.skip(reason="Cached function giving trouble here")
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_patch_solid_tariff(
        self,
        mock_get_our_credentialsrole,
        client,
        solid_tariff_smp1_msp1_data,
        solid_tariff_smp1_msp2_data,
        solid_tariff_smp1_msp1_updated_data,
        smp1_patched_tariff,
        msp1,
        msp2,
        operator,
        tariff_smp1_msp1,
        tariff_smp1_msp2,
    ):
        mock_get_our_credentialsrole.return_value = operator
        url = f"{reverse('solid-tariff-list')}{solid_tariff_smp1_msp1_data['external_id']}/{msp1.party_str()}/"

        SolidTariff.objects.create(**solid_tariff_smp1_msp1_data)
        SolidTariff.objects.create(**solid_tariff_smp1_msp2_data)

        response = client.patch(url, smp1_patched_tariff, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["currency"] == smp1_patched_tariff["currency"]

    @pytest.mark.skip(reason="Cached function giving trouble here")
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_create_solid_tariff_no_ext_id(
        self,
        mock_get_our_credentialsrole,
        client,
        smp1_tariff_data_with_no_external_id,
        msp1,
        msp2,
    ):
        mock_get_our_credentialsrole.return_value = msp1
        url = reverse("solid-tariff-list")
        response = client.post(url, smp1_tariff_data_with_no_external_id, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    @pytest.mark.skip(reason="Cached function giving trouble here")
    @pytest.mark.django_db
    @patch("ocpi22.cpo.tariff.SolidTariffViewSet.permission_classes", [AllowAny])
    @patch("ocpiconnector.ocpi_identities.get_our_credentialsrole")
    def test_update_solid_tariff_no_ext_id(
        self,
        mock_get_our_credentialsrole,
        client,
        smp1_tariff_data_with_no_external_id,
        smp1_tariff_updated_data_with_no_external_id,
        msp1,
        msp2,
    ):
        mock_get_our_credentialsrole.return_value = msp1
        url = reverse("solid-tariff-list")
        client.post(url, smp1_tariff_data_with_no_external_id, format="json")

        url = f"{reverse('solid-tariff-list')}/{msp1.party_str()}/"
        response = client.put(
            url, smp1_tariff_updated_data_with_no_external_id, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert (
            response.data[0]["price_per_kwh"]
            == smp1_tariff_updated_data_with_no_external_id["price_per_kwh"]
        )
