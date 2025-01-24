from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import pytz
import responses
import time_machine
from django.conf import settings
from pydantic_core import PydanticSerializationError
from requests import HTTPError
from responses import matchers

from integrations.hubject.client import HubjectClient
from integrations.hubject.schemas import (
    ActionType,
    OperatorEvseData,
    OperatorID,
    EvseDataRecord,
    EvseID,
    InfoTextType,
    Address,
    GeoCoordinates,
    DecimalDegree,
    Plug,
    ChargingFacility,
    PowerType,
    CalibrationLawDataAvailability,
    AuthenticationMode,
    PaymentOption,
    ValueAddedService,
    Accessibility,
    AccessibilityLocation,
    DynamicInfoAvailable,
    ProductID,
    ProviderIDAsterisk,
    ERoamingPushEVSEPricing,
)
from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.tests.factories import EvseFactory, LocationFactory, CredentialsRoleFactory
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id
from ocpiconnector.party import Party


@pytest.fixture
@time_machine.travel(datetime(2024, 9, 22, 12, 30, 30, 0), tick=False)
def helsinki2_evse(helsinki_connector):
    helsinki_evse = EvseFactory(
        status="RESERVED",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        capabilities=["RFID_READER", "RESERVABLE"],
    )
    helsinki_evse.connectors.set([helsinki_connector])
    return helsinki_evse


@pytest.fixture
def helsinki2_location(
    helsinki_ocpi_master,
    helsinki_operator_details,
    helsinki_sub_operator_details,
    helsinki_owner_details,
    helsinki2_evse,
):
    helsinki_location = LocationFactory(
        publish=True,
        name="Helsinki Supercharger",
        address="Mannerheimintie 1",
        city="Helsinki",
        postal_code="00100",
        state="Uusimaa",
        country="FIN",
        parking_type="ON_STREET",
        latitude=60.1695,
        longitude=24.9354,
        time_zone="Europe/Helsinki",
        ocpi_master=helsinki_ocpi_master,
        operator=helsinki_operator_details,
        suboperator=helsinki_sub_operator_details,
        owner=helsinki_owner_details,
        charging_when_closed=True,
    )

    helsinki_location.evses.add(helsinki2_evse)
    return helsinki_location


@pytest.fixture
@time_machine.travel(datetime(2024, 9, 22, 12, 30, 30, 0), tick=False)
def berlin_evse2_data(berlin_connector):
    berlin_evse_data = EvseFactory(
        uid="berlinevseuid",
        evse_id="FI*ABC*1234*C0*CT",
        status="",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        capabilities=None,
    )
    berlin_evse_data.connectors.set([berlin_connector])
    return berlin_evse_data


@pytest.fixture
def berlin2_location(berlin_ocpi_master, berlin_evse2_data):
    berlin_location = LocationFactory(
        name="Berlin Location",
        address="Ansgarstr. 4",
        city="Wallenhorst",
        postal_code="",
        state="",
        country="DEU",
        latitude=0,
        longitude=0,
        time_zone="Europe/Berlin",
        ocpi_master=berlin_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )
    berlin_location.evses.set([berlin_evse2_data])
    return berlin_location


@pytest.fixture
def emsdetten2_location(emsdetten_ocpi_master, emsdetten2_evse):
    emsdetten_location = LocationFactory(
        name="Emsdetten Location",
        address="Südring 25",
        city="Emsdetten",
        postal_code="38170",
        state="",
        country="DEU",
        latitude=9.360922,
        longitude=47.662249,
        time_zone="Europe/Berlin",
        ocpi_master=emsdetten_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )
    emsdetten_location.evses.set([emsdetten2_evse])
    return emsdetten_location


@pytest.fixture
@time_machine.travel(datetime(2024, 9, 22, 12, 30, 30, 0), tick=False)
def emsdetten2_evse(emsdetten_connector):
    emsdetten_evse = EvseFactory(
        uid="Eemsdettenevseuid",
        evse_id="DE*CPO*1234*C2*CT",
        status="",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 12, 30, 30, 0)),
        capabilities=None,
    )
    emsdetten_evse.connectors.set([emsdetten_connector])
    return emsdetten_evse


class TestHubjectService:
    __hubject_service = HubjectService()

    @patch("ocpi22.models.location.Location.objects.prefetch_related")
    @pytest.mark.django_db
    def test_get_operator_evse_dict(
        self,
        mock_locations,
        berlin2_location,
        emsdetten2_location,
        berlin_op_evse_data,
        emsdetten_op_evse_data,
        berlin_connector,
        emsdetten_connector,
        berlin_tariff,
        emsdetten_tariff,
        berlin_evse2_data,
        emsdetten2_evse,
    ):
        berlin2_location.evses_with_connectors = [berlin_evse2_data]
        emsdetten2_location.evses_with_connectors = [emsdetten2_evse]

        berlin_evse2_data.connectors_with_tariffs = [berlin_connector]
        emsdetten2_evse.connectors_with_tariffs = [emsdetten_connector]

        mock_locations.return_value = [berlin2_location, emsdetten2_location]

        party = Party(country_code="DE", party_id="SMP")
        result = self.__hubject_service.get_operator_evse_data(party)

        assert result == self.expected_berlin_emsdetten_op_evse_data_record()

    def test_get_evse_full_load(
        self,
        berlin_op_evse_data,
        berlin_evse_data_record,
    ):
        operator_id = Party(country_code="DE", party_id="SMP")
        operator_name = berlin_op_evse_data.OperatorName

        with patch(
            "integrations.hubject.services.HubjectService.get_operator_evse_data",
            return_value=berlin_op_evse_data,
        ):
            result = self.__hubject_service.get_evse_full_load_payload(operator_id)
            assert result.ActionType == ActionType.fullLoad
            assert result.OperatorEvseData.OperatorID.root == operator_id.__str__()
            assert result.OperatorEvseData.OperatorName == operator_name
            assert result.OperatorEvseData.EvseDataRecord == [berlin_evse_data_record]

    @responses.activate
    def test_post_evse_full_load(
        self, evse_full_load_payload, hubject_successful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_successful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_full_load(
            operator_id, evse_full_load_payload
        )

        assert result == hubject_successful_response

    @responses.activate
    def test_post_evse_full_load_unsuccessful_response(
        self, evse_full_load_payload, hubject_unsuccessful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        # edit the payload to generate a unsuccessful response from the hubject APIs
        evse_full_load_payload.OperatorEvseData.EvseDataRecord[
            0
        ].ValueAddedServices = []

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_unsuccessful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_full_load(
            operator_id, evse_full_load_payload
        )

        assert result == hubject_unsuccessful_response

    @responses.activate
    def test_execute_evse_full_load_http_error(self, evse_full_load_payload):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            body=HTTPError("HTTP request failed"),
            status=500,
        )

        with pytest.raises(HTTPError):
            service = HubjectService()
            result = service.post_evse_full_load(operator_id, evse_full_load_payload)

            assert result == {
                "success": False,
                "errorType": "HTTP request failed",
                "error": "HTTP request failed",
            }

    def test_execute_evse_full_load_pydantic_error(self):
        operator_id = "DE+MSP"

        payload_mock = MagicMock()
        payload_mock.model_dump_json.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = self.__hubject_service.post_evse_full_load(operator_id, payload_mock)

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }

    @responses.activate
    def test_forbidden_response_for_post_evse_full_load(self, evse_full_load_payload):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            body="<html><head></head><body>Forbidden</body></html>",
            status=403,
        )
        result = self.__hubject_service.post_evse_full_load(
            operator_id, evse_full_load_payload
        )

        assert result == {
            "success": False,
            "errorType": "HTTP Error",
            "error": "403 : <html><head></head><body>Forbidden</body></html>",
        }

    def test_get_default_tariffs_success(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", "0.25")
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", "USD")
        monkeypatch.setattr(
            "django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", "KILOWATT_HOUR"
        )

        result = self.__hubject_service.get_default_tariffs()

        assert result.currency == "USD"
        assert result.price == 0.25
        assert result.price_component.value == "KILOWATT_HOUR"

    def test_get_default_tariffs_missing_env_vars(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", None)
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", None)
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", None)

        with pytest.raises(ValueError) as excinfo:
            self.__hubject_service.get_default_tariffs()
        assert str(excinfo.value) == (
            "Please set DEFAULT_OICP_PRICE, DEFAULT_OICP_CURRENCY, and DEFAULT_OICP_REFERENCE in environment variables"
        )

    def test_get_default_tariffs_partial_env_vars(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", "0.25")
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", None)
        monkeypatch.setattr(
            "django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", "KILOWATT_HOUR"
        )

        with pytest.raises(ValueError) as excinfo:
            self.__hubject_service.get_default_tariffs()
        assert str(excinfo.value) == (
            "Please set DEFAULT_OICP_PRICE, DEFAULT_OICP_CURRENCY, and DEFAULT_OICP_REFERENCE in environment variables"
        )

    def expected_berlin_op_evse_data_record(self):
        return OperatorEvseData(
            OperatorID=OperatorID(root="DE*SMP"),
            OperatorName="Smappee Pvt Ltd",
            EvseDataRecord=[
                EvseDataRecord(
                    deltaType=None,
                    lastUpdate=datetime(
                        2024, 9, 22, 12, 30, 30, 0, tzinfo=timezone.utc
                    ),
                    EvseID=EvseID(root="FI*CPO*Eberlinevseuid"),
                    ChargingPoolID=None,
                    ChargingStationId=None,
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Berlin Location")
                    ],
                    HardwareManufacturer=None,
                    ChargingStationImage=None,
                    SubOperatorName=None,
                    Address=Address(
                        Country="DEU",
                        City="Wallenhorst",
                        Street="Ansgarstr.",
                        PostalCode="",
                        HouseNum="4",
                        Floor=None,
                        Region=None,
                        ParkingFacility=True,
                        ParkingSpot=None,
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="0.000000", Latitude="0.000000"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    DynamicPowerLevel=None,
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.AC_3_PHASE,
                            Voltage=0,
                            Amperage=16,
                            Power=12,
                            ChargingModes=None,
                        )
                    ],
                    RenewableEnergy=False,
                    EnergySource=None,
                    EnvironmentalImpact=None,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
                    MaxCapacity=None,
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.None_],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    AccessibilityLocation=AccessibilityLocation.OnStreet,
                    HotlinePhoneNumber="+3256380211",
                    AdditionalInfo=None,
                    ChargingStationLocationReference=None,
                    GeoChargingPointEntrance=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="0.000000", Latitude="0.000000"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    IsOpen24Hours=True,
                    OpeningTimes=None,
                    HubOperatorID=None,
                    ClearinghouseID=None,
                    IsHubjectCompatible=False,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                )
            ],
        )

    def expected_emsdetten_op_evse_data_record(self):
        return OperatorEvseData(
            OperatorID=OperatorID(root="DE*SMP"),
            OperatorName="Smappee Pvt Ltd",
            EvseDataRecord=[
                EvseDataRecord(
                    deltaType=None,
                    lastUpdate=datetime(
                        2024, 9, 22, 12, 30, 30, 0, tzinfo=timezone.utc
                    ),
                    EvseID=EvseID(root="FI*CPO*EEemsdettenevseuid"),
                    ChargingPoolID=None,
                    ChargingStationId=None,
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Emsdetten Location")
                    ],
                    HardwareManufacturer=None,
                    ChargingStationImage=None,
                    SubOperatorName=None,
                    Address=Address(
                        Country="DEU",
                        City="Emsdetten",
                        Street="dring",
                        PostalCode="38170",
                        HouseNum="25",
                        Floor=None,
                        Region=None,
                        ParkingFacility=True,
                        ParkingSpot=None,
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="47.662249", Latitude="9.360922"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    DynamicPowerLevel=None,
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.AC_3_PHASE,
                            Voltage=0,
                            Amperage=16,
                            Power=1,
                            ChargingModes=None,
                        )
                    ],
                    RenewableEnergy=False,
                    EnergySource=None,
                    EnvironmentalImpact=None,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
                    MaxCapacity=None,
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.None_],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    AccessibilityLocation=AccessibilityLocation.OnStreet,
                    HotlinePhoneNumber="+3256380211",
                    AdditionalInfo=None,
                    ChargingStationLocationReference=None,
                    GeoChargingPointEntrance=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="47.662249", Latitude="9.360922"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    IsOpen24Hours=True,
                    OpeningTimes=None,
                    HubOperatorID=None,
                    ClearinghouseID=None,
                    IsHubjectCompatible=False,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                )
            ],
        )

    def expected_berlin_emsdetten_op_evse_data_record(self):
        berlin_evse_data_record = (
            self.expected_berlin_op_evse_data_record().EvseDataRecord[0]
        )
        emsdetten_evse_data_record = (
            self.expected_emsdetten_op_evse_data_record().EvseDataRecord[0]
        )
        return OperatorEvseData(
            OperatorID=OperatorID(root="DE*SMP"),
            OperatorName="Smappee Pvt Ltd",
            EvseDataRecord=[berlin_evse_data_record, emsdetten_evse_data_record],
        )


@pytest.fixture
def operator():
    country_code = get_our_country_code(OcpiRolesEnum.CPO.value)
    party_id = get_our_party_id(OcpiRolesEnum.CPO.value)

    CredentialsRoleFactory(
        country_code=country_code,
        party_id=party_id,
    )


class TestOICPEvsePricingPushService:
    __hubject_service = HubjectService()
    country_code = get_our_country_code(OcpiRolesEnum.CPO.value)
    party_id = get_our_party_id(OcpiRolesEnum.CPO.value)
    operator = CredentialsRole.objects.filter(
        country_code=country_code, party_id=party_id
    )

    msp1 = CredentialsRole.objects.filter(country_code="DE", party_id="ICD")
    msp2 = CredentialsRole.objects.filter(country_code="DE", party_id="ICE")

    @pytest.mark.django_db
    @pytest.mark.skip
    @patch("ocpi22.models.tariff.SolidTariff.objects.filter")
    def test_get_evse_product_provider_maps(
        self,
        mock_filter,
        msp_de_ice,
        msp_de_icd,
        berlin_evse_data,
        berlin_connector,
        smp1_ocpi_tariff,
        smp1_solid_tariff,
    ):
        party = Party(country_code="FI", party_id="CPO")

        mock_solid_tariff = MagicMock()
        mock_filter.return_value = mock_solid_tariff

        mock_solid_tariff.select_related.return_value = mock_solid_tariff
        mock_solid_tariff.values.return_value = [
            {
                "external_id": "SMP1",
                "price_per_kwh": 0.25,
                "price_per_min": 0.05,
                "msp__country_code": "DE",
                "msp__party_id": "ICE",
            }
        ]

        result = self.__hubject_service.get_evse_product_provider_maps(party)

        key = f"{str(party)}*E{berlin_evse_data.uid}"
        expected_result = {
            key: [
                [
                    ProductID(root="FI*CPO*SMP1*KILOWATT_HOUR*DE*ICE"),
                    ProductID(root="FI*CPO*SMP1*MINUTE*DE*ICE"),
                ],
                [ProviderIDAsterisk(root="DE*ICE"), ProviderIDAsterisk(root="DE*ICE")],
            ]
        }
        assert result[key] == expected_result[key]

    @pytest.mark.django_db
    def test_evse_pricing_product_payload(self):
        key = "FI*CPO*Evse1"
        evse_product_id_provider_id_map = {
            key: [
                [
                    ProductID(root="FI*CPO*SMP1*KILOWATT_HOUR*DE*ICE"),
                    ProductID(root="FI*CPO*SMP1*MINUTE*DE*ICE"),
                ],
                [ProviderIDAsterisk(root="DE*ICE"), ProviderIDAsterisk(root="DE*ICE")],
            ]
        }

        result = self.__hubject_service.get_evse_pricing_product_data_full_load_payload(
            evse_product_id_provider_id_map
        )

        assert isinstance(result, ERoamingPushEVSEPricing)
        assert len(result.EVSEPricing[0].EvseIDProductList) == 2
        assert (
            result.EVSEPricing[0].EvseIDProductList[0].root
            == "FI*CPO*SMP1*KILOWATT_HOUR*DE*ICE"
        )

    @responses.activate
    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load(
        self, evse_pricing_full_load_payload, hubject_successful_response
    ):
        operator_id = "FI*CPO"

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/evse-pricing",
            json=hubject_successful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_pricing_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_pricing_item_full_load(
            operator_id, evse_pricing_full_load_payload
        )

        assert result == hubject_successful_response

    @responses.activate
    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load_unsuccessful_response(
        self, evse_pricing_full_load_payload, hubject_unsuccessful_response
    ):
        operator_id = "FI*CPO"

        # edit the payload to generate a unsuccessful response from the hubject APIs
        evse_pricing_full_load_payload.EVSEPricing = []

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/evse-pricing",
            json=hubject_unsuccessful_response,
            status=400,
            match=[
                matchers.json_params_matcher(
                    evse_pricing_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_pricing_item_full_load(
            operator_id, evse_pricing_full_load_payload
        )

        assert result == hubject_unsuccessful_response

    @responses.activate
    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load_http_error(
        self, evse_pricing_full_load_payload
    ):
        operator_id = "FI*CPO"

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/evse-pricing",
            body=HTTPError("HTTP request failed"),
            status=500,
        )

        with pytest.raises(HTTPError):
            service = HubjectService()
            result = service.post_evse_pricing_item_full_load(
                operator_id, evse_pricing_full_load_payload
            )

            assert result == {
                "success": False,
                "errorType": "HTTP request failed",
                "error": "HTTP request failed",
            }

    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load_pydantic_error(self):
        operator_id = "DE+MSP"

        payload_mock = MagicMock()
        payload_mock.model_dump_json.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = self.__hubject_service.post_evse_pricing_item_full_load(
            operator_id, payload_mock
        )

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }


class TestHubjectClient:
    def test_hubject_client_init(self):
        HubjectClient(rewrite_cert_files=True)
