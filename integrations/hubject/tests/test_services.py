import json
import re
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import pytz
import responses
import time_machine
from django.conf import settings
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError
from requests import HTTPError
from responses import matchers

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
    ReferenceUnit,
    AdditionalReference,
    PricingProductDataRecord,
    AdditionalReferenceChoice,
    CurrencyID,
    PricingProductData,
    ERoamingPushPricingProductData,
    ProductID,
    ProviderIDAsterisk,
    HubjectDefaultTariff,
    HubjectPriceComponent,
    ERoamingPushEvseStatus,
    OperatorEvseStatus,
    EvseStatusRecordItem,
    EvseStatus,
)
from integrations.hubject.services import (
    HubjectService,
)
from integrations.hubject.tests.test_mappings import get_timezone_offset
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.location import Location, Evse
from ocpi22.models.tariff import SolidTariff
from ocpi22.tests.factories import (
    EvseFactory,
    LocationFactory,
    PricingProductDataFactory,
)
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party, get_our_credentialsrole
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
        payload_mock.model_dump.side_effect = PydanticSerializationError(
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

    def test_get_default_tariffs_minus_ocip_price(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", "-0.25")
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", "EUR")
        monkeypatch.setattr(
            "django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", "KILOWATT_HOUR"
        )

        with pytest.raises(ValueError) as excinfo:
            self.__hubject_service.get_default_tariffs()
        assert str(excinfo.value) == ("DEFAULT_OICP_PRICE must be positive")

    def test_hubject_default_returns_currency_success(self):
        default_tariff = HubjectDefaultTariff(
            currency="USD", price=0.34, price_component=HubjectPriceComponent.KWH
        )
        assert default_tariff.currency == "USD"

    def test_hubject_default_raises_validation_error_given_invalid_currency(self):
        with pytest.raises(ValueError, match="Invalid currency: INV"):
            HubjectDefaultTariff(
                currency="INV", price=0.34, price_component=HubjectPriceComponent.KWH
            )

    def test_hubject_default_raises_validation_error_given_blank_currency(self):
        with pytest.raises(ValueError, match="Invalid currency: "):
            HubjectDefaultTariff(
                currency="", price=0.34, price_component=HubjectPriceComponent.KWH
            )

    @pytest.mark.parametrize(
        "price_component, expected",
        [
            ("KILOWATT_HOUR", HubjectPriceComponent.KWH),
            ("MINUTE", HubjectPriceComponent.MINUTE),
            ("HOUR", HubjectPriceComponent.HOUR),
        ],
    )
    def test_get_price_component_success(self, price_component, expected):
        price_component = HubjectDefaultTariff.get_price_component(price_component)
        assert price_component == expected

    def test_get_price_component_raises_value_error_when_given_invalid_price_component(
        self,
    ):
        with pytest.raises(ValueError):
            HubjectDefaultTariff.get_price_component("INVALID")

    @pytest.mark.django_db
    def test_get_operator_evse_data_without_locations_returns_none(self):
        party = get_our_party(OcpiRolesEnum.CPO)
        Location.objects.filter(
            ocpi_master__party_id=party.party_id,
            ocpi_master__country_code=party.country_code,
        ).delete()

        result = self.__hubject_service.get_operator_evse_data(party)

        assert result is None

    @pytest.mark.django_db
    def test_get_operator_evse_data_raises_connector_tariff_not_found_when_no_tariffs_assigned_to_evses(
        self, helsinki_location
    ):
        party = get_our_party(OcpiRolesEnum.CPO)

        evse = helsinki_location.evses.first()
        connector = evse.connectors.first()
        connector.tariff_ids.set([])
        connector.save()

        with pytest.raises(ConnectorTariffNotFoundError):
            self.__hubject_service.get_operator_evse_data(party)

    @pytest.mark.django_db
    def test_get_operator_evse_data_without_evse_data_records_return_none(self):
        party = get_our_party(OcpiRolesEnum.CPO)
        Location.objects.filter(
            ocpi_master__party_id=party.party_id,
            ocpi_master__country_code=party.country_code,
        ).delete()

        LocationFactory()

        result = self.__hubject_service.get_operator_evse_data(party)

        assert result is None

    @pytest.mark.django_db
    def test_get_evse_full_load_payload_without_operator_evse_data_returns_none(self):
        party = get_our_party(OcpiRolesEnum.CPO)
        Location.objects.filter(
            ocpi_master__party_id=party.party_id,
            ocpi_master__country_code=party.country_code,
        ).delete()

        result = self.__hubject_service.get_evse_full_load_payload(party)
        assert result is None

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
                    EvseID=EvseID(root="FI*CPO*EBERLINEVSEUID"),
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
                        TimeZone=get_timezone_offset("Europe/Berlin"),
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
                    EvseID=EvseID(root="FI*CPO*EEEMSDETTENEVSEUID"),
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
                        Street="Südring",
                        PostalCode="38170",
                        HouseNum="25",
                        Floor=None,
                        Region=None,
                        ParkingFacility=True,
                        ParkingSpot=None,
                        TimeZone=get_timezone_offset("Europe/Berlin"),
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


class TestOICPDynamicPricingService:
    hubject_service = HubjectService()

    @patch("ocpi22.models.tariff.SolidTariff.objects.filter", name="mock_solid_tariffs")
    @pytest.mark.django_db
    def test_get_all_pricing_products(
        self, mock_solid_tariffs, smp1_solid_tariff, smp2_solid_tariff, monkeypatch
    ):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", "0.3")
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", "EUR")
        monkeypatch.setattr(
            "django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", "KILOWATT_HOUR"
        )

        expected_result = self.get_expected_pricing_product_data()

        mock_solid_tariffs.return_value = [smp1_solid_tariff, smp2_solid_tariff]

        result = self.hubject_service.get_all_pricing_products(
            get_our_party(OcpiRolesEnum.CPO)
        )

        assert result == expected_result

    @patch("ocpi22.models.tariff.SolidTariff.objects.filter", name="mock_solid_tariffs")
    @pytest.mark.django_db
    def test_get_all_pricing_products_with_invalid_env_variables(
        self,
        mock_solid_tariffs,
        monkeypatch,
        msp_de_ice,
        smp1_solid_tariff,
        smp2_solid_tariff,
    ):
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE", None)
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_CURRENCY", None)
        monkeypatch.setattr("django.conf.settings.DEFAULT_OICP_PRICE_REFERENCE", None)

        mock_solid_tariffs.return_value = [smp1_solid_tariff, smp2_solid_tariff]

        with pytest.raises(
            ValueError,
            match="Please set DEFAULT_OICP_PRICE, DEFAULT_OICP_CURRENCY, and DEFAULT_OICP_REFERENCE in environment variables",
        ):
            self.hubject_service.get_all_pricing_products(
                get_our_party(OcpiRolesEnum.CPO)
            )

    @patch("ocpi22.models.tariff.SolidTariff.objects.filter", name="mock_solid_tariffs")
    @pytest.mark.django_db
    def test_get_all_pricing_products_with_no_solid_tariffs_raises_does_not_exists_error(
        self, mock_solid_tariffs, monkeypatch, msp_de_ice
    ):
        mock_solid_tariffs.return_value = []
        expected_message = (
            f"No SolidTariffs found for {str(get_our_party(OcpiRolesEnum.CPO))}"
        )

        with pytest.raises(SolidTariff.DoesNotExist, match=re.escape(expected_message)):
            self.hubject_service.get_all_pricing_products(
                get_our_party(OcpiRolesEnum.CPO)
            )

    def test_get_push_pricing_product_data_payload_success(self):
        pricing_product_data = PricingProductDataFactory()
        action_type = ActionType.fullLoad

        result = self.hubject_service.get_push_pricing_product_data_payload(
            pricing_product_data, action_type
        )

        assert isinstance(result, ERoamingPushPricingProductData)
        assert result.ActionType == action_type
        assert result.PricingProductData == pricing_product_data

    def test_get_push_pricing_product_data_payload_invalid_pricing_data(self):
        pricing_product_data = None
        action_type = ActionType.fullLoad

        with pytest.raises(ValidationError):
            self.hubject_service.get_push_pricing_product_data_payload(
                pricing_product_data, action_type
            )

    @responses.activate
    def test_post_pricing_products_full_load(
        self, pricing_products_full_load_payload, hubject_successful_response
    ):
        operator_id = (
            pricing_products_full_load_payload.PricingProductData.OperatorID.root
        )

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/pricing-products",
            json=hubject_successful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    pricing_products_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.hubject_service.post_pricing_products_full_load(
            operator_id, pricing_products_full_load_payload
        )

        assert result == hubject_successful_response

    @responses.activate
    def test_post_pricing_products_full_load_returns_400_when_pricing_default_price_is_none(
        self, pricing_products_full_load_payload, hubject_unsuccessful_response
    ):
        operator_id = (
            pricing_products_full_load_payload.PricingProductData.OperatorID.root
        )

        # edit the payload to generate a unsuccessful response from the hubject APIs
        pricing_products_full_load_payload.PricingProductData.PricingDefaultPrice = None

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/pricing-products",
            json=hubject_unsuccessful_response,
            status=400,
            match=[
                matchers.json_params_matcher(
                    pricing_products_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.hubject_service.post_pricing_products_full_load(
            operator_id, pricing_products_full_load_payload
        )
        response_content = json.loads(result["error"].split(":", 1)[1])
        assert isinstance(response_content, dict)
        assert response_content == hubject_unsuccessful_response

    @responses.activate
    def test_post_pricing_products_full_load_pydantic_error_when_model_dump_to_json(
        self, hubject_unsuccessful_response
    ):
        operator_id = "DE+MSP"

        payload_mock = MagicMock()
        payload_mock.model_dump.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = self.hubject_service.post_pricing_products_full_load(
            operator_id, payload_mock
        )

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }

    def get_expected_pricing_product_data(self):
        return PricingProductData(
            OperatorID=OperatorID(root="FI*CPO"),
            OperatorName="Smappee Pvt Ltd",
            ProviderID=ProviderIDAsterisk(root="DE*ICE"),
            PricingDefaultPrice=0.3,
            PricingDefaultPriceCurrency=CurrencyID(root="EUR"),
            PricingDefaultReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
            PricingProductDataRecords=[
                PricingProductDataRecord(
                    ProductID=ProductID(root="FI*CPO*SMP1*KILOWATT_HOUR*DE*ICE"),
                    ReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
                    ProductPriceCurrency=CurrencyID(root="EUR"),
                    PricePerReferenceUnit=0.2,
                    MaximumProductChargingPower=0.0,
                    IsValid24hours=True,
                    ProductAvailabilityTimes=[],
                    AdditionalReferences=[
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.START_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=0.3,
                        )
                    ],
                ),
                PricingProductDataRecord(
                    ProductID=ProductID(root="FI*CPO*SMP1*MINUTE*DE*ICE"),
                    ReferenceUnit=ReferenceUnit(root="MINUTE"),
                    ProductPriceCurrency=CurrencyID(root="EUR"),
                    PricePerReferenceUnit=0.3,
                    MaximumProductChargingPower=0.0,
                    IsValid24hours=True,
                    ProductAvailabilityTimes=[],
                    AdditionalReferences=[
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.START_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=0.3,
                        )
                    ],
                ),
                PricingProductDataRecord(
                    ProductID=ProductID(root="FI*CPO*SMP2*KILOWATT_HOUR*DE*ICE"),
                    ReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
                    ProductPriceCurrency=CurrencyID(root="EUR"),
                    PricePerReferenceUnit=0.2,
                    MaximumProductChargingPower=0.0,
                    IsValid24hours=True,
                    ProductAvailabilityTimes=[],
                    AdditionalReferences=[
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.START_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=0.3,
                        )
                    ],
                ),
                PricingProductDataRecord(
                    ProductID=ProductID(root="FI*CPO*SMP2*MINUTE*DE*ICE"),
                    ReferenceUnit=ReferenceUnit(root="MINUTE"),
                    ProductPriceCurrency=CurrencyID(root="EUR"),
                    PricePerReferenceUnit=0.3,
                    MaximumProductChargingPower=0.0,
                    IsValid24hours=True,
                    ProductAvailabilityTimes=[],
                    AdditionalReferences=[
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.START_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=0.3,
                        )
                    ],
                ),
            ],
        )


@pytest.mark.django_db
class TestPushEvseStatus:
    def test_get_payload_successfully(self, monkeypatch):
        evse = EvseFactory(status="AVAILABLE")
        ocpi_master = evse.location.ocpi_master
        operator_id = Party(
            country_code=ocpi_master.country_code, party_id=ocpi_master.party_id
        )
        result = HubjectService._get_evse_status_update_payload(
            evse, str(operator_id), "HelsinkiOperator"
        )

        assert result == ERoamingPushEvseStatus(
            action_type=ActionType.update,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=str(operator_id)),
                operator_name="HelsinkiOperator",
                evse_status_record=[
                    EvseStatusRecordItem(
                        EvseID=EvseID(root=evse.evse_id),
                        evse_id=evse.evse_id,
                        evse_status=EvseStatus.Available,
                    )
                ],
            ),
        )

    def test_get_payload_with_invalid_evse_status_return_value_error(self):
        evse = EvseFactory(status="INVALID")
        ocpi_master = evse.location.ocpi_master
        operator_id = Party(
            country_code=ocpi_master.country_code, party_id=ocpi_master.party_id
        )

        with pytest.raises(ValueError, match="Invalid OCPI status \\[INVALID\\] found"):
            HubjectService._get_evse_status_update_payload(
                evse, str(operator_id), "HelsinkiOperator"
            )

    @pytest.mark.parametrize("operator_id", ["DE*SMPW", "KL1*CPO", "INVALID", None])
    def test_get_payload_with_invalid_operator_id(self, operator_id):
        evse = EvseFactory(status="INVALID")
        with pytest.raises(ValidationError):
            HubjectService._get_evse_status_update_payload(
                evse, str(operator_id), "HelsinkiOperator"
            )

    @responses.activate
    def test_post_evse_status_success(self):
        evse = EvseFactory(status="AVAILABLE")

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v21/operators/FI*CPO/status-records",
            json={"success": True},
            status=200,
            match=[
                matchers.json_params_matcher(
                    HubjectService._get_evse_status_update_payload(
                        evse, "FI*CPO", evse.location.ocpi_master.business_details.name
                    ).model_dump(mode="json", by_alias=True)
                )
            ],
        )
        with patch(
            "integrations.hubject.services.send_hubject_request.delay",
            return_value=AsyncMock(),
        ) as mock_send_request:
            HubjectService.post_eroaming_push_evse_status(evse, retries=0)
            assert mock_send_request.call_count == 1

    def test_post_evse_status_without_evse(self, caplog):
        HubjectService.post_eroaming_push_evse_status(None, retries=0)
        assert caplog.records[0].message == "No EVSE provided for hubject status update"

    def test_post_evse_status_with_incorrect_payload(self, caplog):
        evse = EvseFactory(status="AVAILABLE")
        evse.evse_id = "INVALID_EVSE_ID"
        HubjectService.post_eroaming_push_evse_status(evse, retries=0)
        assert (
            "Failed to create payload for EVSE status update"
            in caplog.records[0].message
        )

    def test_post_evse_status_with_value_error_in_payload_returns_none(self, caplog):
        evse = EvseFactory(status="AVAILABLE")
        evse.evse_id = "INVALID_EVSE_ID"
        with patch(
            "integrations.hubject.services.HubjectService._get_evse_status_update_payload",
            side_effect=ValueError("Invalid OCPI status [INVALID_EVSE_ID] found"),
        ):
            result = HubjectService.post_eroaming_push_evse_status(evse, retries=0)
            assert result is None
            assert "Invalid OCPI status [INVALID_EVSE_ID] found" in caplog.text

    def test_post_evse_status_with_full_load_true_uses_full_load_payload(self):
        evse = EvseFactory(status="AVAILABLE")
        get_our_credentialsrole.cache_clear()
        our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v21/operators/FI*CPO/status-records",
            json={"success": True},
            status=200,
            match=[
                matchers.json_params_matcher(
                    HubjectService._get_evse_status_full_load_payload(
                        f"{our_role.country_code}*{our_role.party_id}", our_role
                    ).model_dump(mode="json", by_alias=True)
                )
            ],
        )
        with patch(
            "integrations.hubject.services.send_hubject_request.delay",
            return_value=AsyncMock(),
        ):
            with patch(
                "integrations.hubject.services.HubjectService._get_evse_status_full_load_payload"
            ) as mock_get_payload:
                HubjectService.post_eroaming_push_evse_status(
                    evse, retries=0, full_load=True
                )
                assert mock_get_payload.call_count == 1

    def test_get_evse_status_full_load_payload_success(self, operator_fi_cpo):
        get_our_credentialsrole.cache_clear()
        our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
        location = LocationFactory(uid="porvoo", ocpi_master=operator_fi_cpo)
        EvseFactory(uid="Evse1", status="AVAILABLE", location=location)
        EvseFactory(uid="Evse2", status="AVAILABLE", location=location)
        result = HubjectService._get_evse_status_full_load_payload(
            f"{our_role.country_code}*{our_role.party_id}", our_role
        )
        assert result.model_dump(mode="json", by_alias=True) == {
            "ActionType": "fullLoad",
            "OperatorEvseStatus": {
                "EvseStatusRecord": [
                    {"EvseID": "FI*CPO*EEVSE1", "EvseStatus": "Available"},
                    {"EvseID": "FI*CPO*EEVSE2", "EvseStatus": "Available"},
                ],
                "OperatorID": "FI*CPO",
                "OperatorName": "Smappee Pvt Ltd",
            },
        }

    def test_get_evse_status_full_load_payload_with_no_evses(self, caplog):
        get_our_credentialsrole.cache_clear()
        our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
        Evse.objects.all().delete()
        result = HubjectService._get_evse_status_full_load_payload(
            f"{our_role.country_code}*{our_role.party_id}", our_role
        )
        assert result is None
        assert "No EVSE records found" in caplog.text

    def test_get_evse_status_full_load_payload_with_invalid_evse_id(
        self, caplog, operator_fi_cpo
    ):
        get_our_credentialsrole.cache_clear()
        our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
        location = LocationFactory(uid="porvoo", ocpi_master=operator_fi_cpo)
        EvseFactory(uid="Evse1", status="INVALID", location=location)
        with pytest.raises(ValueError, match="Invalid OCPI status \\[INVALID\\] found"):
            HubjectService._get_evse_status_full_load_payload(
                f"{our_role.country_code}*{our_role.party_id}", our_role
            )
            HubjectService._get_evse_status_full_load_payload(
                f"{our_role.country_code}*{our_role.party_id}", our_role
            )


class TestPostEroamingChargeDetailRecord:
    @pytest.fixture
    def cdr_successful_response(self):
        return {
            "message": "Sent CDR to hubject",
            "success": True,
        }

    @pytest.fixture
    def cdr_unsuccessful_response(self):
        return {
            "success": False,
            "errorType": "Hubject server Error",
            "error": "Hubject server returned 500. Retrying...",
        }

    def test_post_eroaming_cdr_with_cdr_and_session_id_none_returns_unsuccessful_response(
        self,
    ):
        operator_id = "FI*CPO"
        ocpi_cdr = None

        result = HubjectService.post_eroaming_charge_detail_record(
            operator_id, ocpi_cdr
        )

        assert result == {
            "success": False,
            "errorType": "Invalid Input",
            "error": "Either CDR or session_id must be provided.",
        }

    @pytest.mark.django_db
    def test_post_eroaming_cdr_with_non_existing_cdr_returns_unsuccessful_response(
        self,
    ):
        operator_id = "FI*CPO"

        result = HubjectService.post_eroaming_charge_detail_record(
            operator_id, None, session_id="session_without_cdr"
        )

        assert result == {
            "success": False,
            "errorType": "Invalid Input",
            "error": "No CDR found for session_id session_without_cdr.",
        }

    @pytest.mark.django_db
    def test_post_eroaming_cdr_with_cdr_route_through_oicp_false_returns_unsuccessful_response(
        self, ocpi_cdr, monkeypatch
    ):
        operator_id = "FI*CPO"
        monkeypatch.setattr(
            type(ocpi_cdr.session), "route_through_oicp", property(lambda self: False)
        )
        result = HubjectService.post_eroaming_charge_detail_record(
            operator_id, None, session_id=ocpi_cdr.session.uid
        )

        assert result == {
            "success": False,
            "errorType": "Incompatible CDR",
            "error": f"CDR with session id {ocpi_cdr.session.uid} has not routed through OICP",
        }

    @responses.activate
    @pytest.mark.django_db
    def test_post_eroaming_cdr_with_valid_data_returns_successful_hubject_response(
        self, ocpi_cdr, cdr_successful_response
    ):
        operator_id = "FI*CPO"

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}cdrmgmt/v22/operators/{operator_id}/charge-detail-record",
            json=cdr_successful_response,
            status=200,
        )

        result = HubjectService.post_eroaming_charge_detail_record(
            operator_id, ocpi_cdr
        )
        assert result == cdr_successful_response
