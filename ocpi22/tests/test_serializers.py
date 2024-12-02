from unittest.mock import patch

import pytest

from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.serializers import SolidTariffSerializer
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff
from ocpi22.tests.factories import CredentialsRoleFactory
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


class TestSolidTariffSerializer:
    country_code = get_our_country_code(OcpiRolesEnum.CPO.value)
    party_id = get_our_party_id(OcpiRolesEnum.CPO.value)
    operator = CredentialsRole.objects.filter(
        country_code=country_code, party_id=party_id
    )
    msp1 = CredentialsRole.objects.filter(country_code="DE", party_id="SMP")
    msp2 = CredentialsRole.objects.filter(country_code="DE", party_id="ICE")

    def setup_method(self):
        CredentialsRoleFactory(
            country_code=self.country_code,
            party_id=self.party_id,
        )
        CredentialsRoleFactory(
            country_code="DE",
            party_id="ICE",
        )
        CredentialsRoleFactory(
            country_code="DE",
            party_id="SMP",
        )

    @pytest.mark.django_db
    def test_create_solid_tariff(self, smp1_solid_tariff_data):
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        tariff = serializer.create(smp1_solid_tariff_data)

        solid_tariffs = SolidTariff.objects.filter(uid=tariff.uid)

        assert len(solid_tariffs) == 1
        assert solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert solid_tariffs[0].msp is None
        assert tariff.uid == smp1_solid_tariff_data["uid"]

    @pytest.mark.django_db
    def test_create_multiple_solid_tariffs_with_one_msp(self, smp1_solid_tariff_data):
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp1.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        tariff = serializer.create(smp1_solid_tariff_data)

        solid_tariffs = SolidTariff.objects.filter(uid=tariff.uid).all()

        assert len(solid_tariffs) == 1
        assert solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert solid_tariffs[0].msp == smp1_solid_tariff_data["msps"][0]
        assert tariff.uid == smp1_solid_tariff_data["uid"]

    @pytest.mark.django_db
    def test_create_multiple_solid_tariffs_with_different_msps(
        self, smp1_solid_tariff_data
    ):
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp1.first(), self.msp2.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        tariff = serializer.create(smp1_solid_tariff_data)

        solid_tariffs = SolidTariff.objects.filter(uid=tariff.uid).all()

        assert len(solid_tariffs) == 2
        assert solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert solid_tariffs[1].uid == smp1_solid_tariff_data["uid"]

        assert solid_tariffs[0].msp == smp1_solid_tariff_data["msps"][0]
        assert solid_tariffs[1].msp == smp1_solid_tariff_data["msps"][1]
        assert tariff.uid == smp1_solid_tariff_data["uid"]

    # @pytest.mark.django_db
    # def test_create_solid_tariff_with_invalid_msp(self, smp1_solid_tariff_data):
    #     smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
    #     smp1_solid_tariff_data["msps"] = ["DE*EMP"]
    #
    #     serializer = SolidTariffSerializer(smp1_solid_tariff_data)
    #     with pytest.raises(ValueError):
    #         tariff = serializer.create(smp1_solid_tariff_data)

    @patch("ocpi22.cpo.serializers.SolidTariff.objects.filter")
    @pytest.mark.django_db
    def test_update_solid_tariff(
        self,
        solid_tariff_filter,
        smp1_solid_tariff_data,
        smp1_solid_tariff,
        tariff_smp1,
    ):
        solid_tariff_filter.return_value = [smp1_solid_tariff]
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp1.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        serializer.update_solid_tariff(tariff_smp1, smp1_solid_tariff_data)
        all_solid_tariffs = SolidTariff.objects.all()

        assert len(all_solid_tariffs) == 1
        assert all_solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert all_solid_tariffs[0].msp.party_str() == "DE*SMP"

    @patch("ocpi22.cpo.serializers.SolidTariff.objects.filter")
    @pytest.mark.django_db
    def test_update_solid_tariff_with_different_msp(
        self,
        solid_tariff_filter,
        smp1_solid_tariff_data,
        smp1_solid_tariff,
        tariff_smp1,
    ):
        solid_tariff_filter.return_value = [smp1_solid_tariff]
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp2.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        serializer.update_solid_tariff(tariff_smp1, smp1_solid_tariff_data)
        all_solid_tariffs = SolidTariff.objects.all()

        assert len(all_solid_tariffs) == 1
        assert all_solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert all_solid_tariffs[0].msp.party_str() == "DE*ICE"

    @patch("ocpi22.cpo.serializers.SolidTariff.objects.filter")
    @pytest.mark.django_db
    def test_update_solid_tariff_with_multiple_msps(
        self,
        solid_tariff_filter,
        smp1_solid_tariff_data,
        smp1_solid_tariff,
        tariff_smp1,
    ):
        solid_tariff_filter.return_value = [smp1_solid_tariff]
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp1.first(), self.msp2.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        serializer.update_solid_tariff(tariff_smp1, smp1_solid_tariff_data)
        all_solid_tariffs = SolidTariff.objects.all()

        assert len(all_solid_tariffs) == 2
        assert all_solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert all_solid_tariffs[0].msp.party_str() == "DE*SMP"
        assert all_solid_tariffs[1].msp.party_str() == "DE*ICE"

    @patch("ocpi22.cpo.serializers.SolidTariff.objects.filter")
    @pytest.mark.django_db
    def test_update_solid_tariff_with_fewer_msps(
        self,
        solid_tariff_filter,
        smp1_solid_tariff_data,
        smp1_solid_tariff,
        tariff_smp1,
        smp1_solid_tariff_with_msp1,
    ):
        solid_tariff_filter.return_value = [
            smp1_solid_tariff,
            smp1_solid_tariff_with_msp1,
        ]
        smp1_solid_tariff_data["ocpi_master"] = self.operator.first()
        smp1_solid_tariff_data["msps"] = [self.msp1.first()]

        serializer = SolidTariffSerializer(smp1_solid_tariff_data)
        serializer.update_solid_tariff(tariff_smp1, smp1_solid_tariff_data)
        all_solid_tariffs = SolidTariff.objects.all()

        assert len(all_solid_tariffs) == 1
        assert all_solid_tariffs[0].uid == smp1_solid_tariff_data["uid"]
        assert all_solid_tariffs[0].msp.party_str() == "DE*SMP"
