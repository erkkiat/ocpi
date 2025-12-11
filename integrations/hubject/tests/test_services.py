import re
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock, Mock

import pytest
import pytz
import responses
import time_machine
from django.conf import settings
from django.test import override_settings
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError
from requests import HTTPError
from responses import matchers
from rest_framework import status

from integrations.hubject.exceptions import HubjectRemoteCommandError
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
    ProductID,
    ProviderIDAsterisk,
    HubjectDefaultTariff,
    HubjectPriceComponent,
    ERoamingPushEvseStatus,
    OperatorEvseStatus,
    EvseStatusRecordItem,
    EvseStatus,
    ERoamingAuthorizeRemoteStart,
    Identification,
    ERoamingAcknowledgment,
    ProviderID,
    StatusCode,
    RemoteIdentification,
    EvcoID,
    ERoamingAuthorizeRemoteStop,
    SessionID,
)
from integrations.hubject.services import (
    HubjectService,
)
from integrations.hubject.tests.test_mappings import get_timezone_offset
from ocpi22.choices import OcpiRolesEnum
from ocpi22.commands.repository import SessionRepository
from ocpi22.cpo.repositories import CredentialsRepository
from ocpi22.models.location import Location, Evse
from ocpi22.models.session import Session
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.util import OCPIResponse, Ocpi
from ocpi22.tests.factories import (
    EvseFactory,
    LocationFactory,
    PricingProductDataFactory,
    CredentialsRoleFactory,
    ConnectorFactory,
    OCPISessionFactory,
    CredentialsFactory,
    BusinessDetailsFactory,
)
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party
from ocpiconnector.ocpi_identities import (
    get_our_country_code,
    get_our_party_id,
    get_our_credentialsrole,
)
from ocpiconnector.party import Party
from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.factories import WebhookFactory
from ocpi22.util import build_absolute_uri


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
        hubject_credentials,
    ):
        berlin2_location.evses_with_connectors = [berlin_evse2_data]
        emsdetten2_location.evses_with_connectors = [emsdetten2_evse]

        berlin_evse2_data.connectors_with_tariffs = [berlin_connector]
        emsdetten2_evse.connectors_with_tariffs = [emsdetten_connector]

        mock_locations.return_value = [berlin2_location, emsdetten2_location]

        party = Party(country_code="DE", party_id="SMP")
        result = self.__hubject_service.get_operator_evse_data(party)

        assert result == self.expected_berlin_op_evse_data_record()

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
    @pytest.mark.django_db
    def test_forbidden_response_for_post_evse_full_load(
        self, evse_full_load_payload, hubject_credentials
    ):
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
        self, helsinki_location, hubject_credentials
    ):
        party = helsinki_location.ocpi_master.get_party()

        evse = helsinki_location.evses.first()
        connector = evse.connectors.first()
        connector.tariff_ids.set([])
        connector.save()

        with pytest.raises(ConnectorTariffNotFoundError):
            self.__hubject_service.get_operator_evse_data(party)

    @pytest.mark.django_db
    def test_get_operator_evse_data_without_evse_data_records_return_none(
        self, hubject_credentials
    ):
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
                    IsHubjectCompatible=True,
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
                    IsHubjectCompatible=True,
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

    return CredentialsRoleFactory(
        country_code=country_code,
        party_id=party_id,
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
        assert result["error"]["message"] == "Error parsing/validating JSON."
        assert "must not be empty" in result["error"]["errors"][0]

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

        result = self.hubject_service.get_evse_product_provider_maps(party)

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
                ProductID(root="OCPITARIFF1*SMP1"),
                ProductID(root="OCPITARIFF2*SMP2"),
            ]
        }

        result = self.hubject_service.get_evse_pricing_product_data_full_load_payload(
            evse_product_id_provider_id_map
        )

        assert len(result.EVSEPricing[0].EvseIDProductList) == 2
        assert result.EVSEPricing[0].EvseIDProductList[0].root == "OCPITARIFF1*SMP1"
        assert result.EVSEPricing[0].EvseIDProductList[1].root == "OCPITARIFF2*SMP2"

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
        result = self.hubject_service.post_evse_pricing_item_full_load(
            evse_pricing_full_load_payload
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
        result = self.hubject_service.post_evse_pricing_item_full_load(
            evse_pricing_full_load_payload
        )

        assert result == hubject_unsuccessful_response

    @responses.activate
    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load_http_error(
        self, evse_pricing_full_load_payload
    ):
        operator_id = "FI*CPO"

        responses.add_callback(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/evse-pricing",
            callback=lambda request: HTTPError("HTTP request failed"),
        )

        with pytest.raises(HTTPError):
            service = HubjectService()
            service.post_evse_pricing_item_full_load(evse_pricing_full_load_payload)

    @pytest.mark.django_db
    def test_post_evse_pricing_products_full_load_pydantic_error(self):
        payload_mock = MagicMock()
        payload_mock.model_dump.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = self.hubject_service.post_evse_pricing_item_full_load(payload_mock)

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }

    @pytest.mark.django_db
    def test_get_evse_product_maps_returns_none_when_hubject_role_does_not_exists(self):
        result = self.hubject_service.get_evse_product_maps()
        assert result is None

    @pytest.mark.django_db
    def test_evse_product_id_map_generator_returns_the_map_in_proper_format(
        self, smp1_solid_tariff, smp2_solid_tariff
    ):
        location = LocationFactory(
            ocpi_master=smp1_solid_tariff.operator, roaming_enabled=True
        )
        ConnectorFactory(
            tariff_ids=[smp1_solid_tariff.ocpi_tariff],
            evse=EvseFactory(uid="EVSE01", location=location),
        )
        ConnectorFactory(
            tariff_ids=[smp2_solid_tariff.ocpi_tariff],
            evse=EvseFactory(uid="EVSE02", location=location),
        )

        evses = CredentialsRepository.get_evses_by_party(
            CredentialsFactory(), smp1_solid_tariff.operator.get_party()
        )
        result = self.hubject_service.evse_product_id_map_generator(evses)
        assert result == {
            "FI*CPO*EEVSE01": ["OCPITARIFF1*SMP1"],
            "FI*CPO*EEVSE02": ["OCPITARIFF2*SMP2"],
        }

    def get_expected_pricing_product_data(self):
        return PricingProductData(
            OperatorID=OperatorID(root="FI*CPO"),
            OperatorName="Smappee Pvt Ltd",
            ProviderID=ProviderIDAsterisk(root="*"),
            PricingDefaultPrice=0.3,
            PricingDefaultPriceCurrency=CurrencyID(root="EUR"),
            PricingDefaultReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
            PricingProductDataRecords=[
                PricingProductDataRecord(
                    ProductID=ProductID(root="OCPITARIFF1*SMP1"),
                    ReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
                    ProductPriceCurrency=CurrencyID(root="EUR"),
                    PricePerReferenceUnit=Decimal("0.200"),
                    MaximumProductChargingPower=0.0,
                    IsValid24hours=True,
                    ProductAvailabilityTimes=[],
                    AdditionalReferences=[
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.START_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=Decimal("0.300"),
                        ),
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.PARKING_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=Decimal("0.300"),
                        ),
                    ],
                ),
                PricingProductDataRecord(
                    ProductID=ProductID(root="OCPITARIFF2*SMP2"),
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
                        ),
                        AdditionalReference(
                            AdditionalReference=AdditionalReferenceChoice.PARKING_FEE.value,
                            AdditionalReferenceUnit=ReferenceUnit(root="HOUR"),
                            PricePerAdditionalReferenceUnit=0.3,
                        ),
                    ],
                ),
            ],
        )


@pytest.mark.django_db
class TestPushEvseStatus:
    def test_get_payload_successfully(self, monkeypatch):
        role = CredentialsRoleFactory(
            business_details=BusinessDetailsFactory(name="HelsinkiOperator")
        )
        location = LocationFactory(ocpi_master=role, name="HelsinkiLocation")
        evse = EvseFactory(status="AVAILABLE", location=location)
        result = HubjectService._get_evse_status_update_payload(evse)

        assert result == ERoamingPushEvseStatus(
            action_type=ActionType.update,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=str(location.ocpi_master.get_party())),
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
        with pytest.raises(ValueError, match="Invalid OCPI status \\[INVALID\\] found"):
            HubjectService._get_evse_status_update_payload(evse)

    @responses.activate
    @pytest.mark.django_db
    def test_post_evse_status_success(self, hubject_credentials):
        evse = EvseFactory(status="AVAILABLE")

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v21/operators/FI*CPO/status-records",
            json={"success": True},
            status=200,
            match=[
                matchers.json_params_matcher(
                    HubjectService._get_evse_status_update_payload(evse).model_dump(
                        mode="json", by_alias=True
                    )
                )
            ],
        )
        with patch(
            "integrations.hubject.services.send_hubject_request.delay",
            return_value=AsyncMock(),
        ) as mock_send_request:
            HubjectService.post_eroaming_push_evse_status(evse)
            assert mock_send_request.call_count == 1

    def test_post_evse_status_without_evse(self, caplog):
        HubjectService.post_eroaming_push_evse_status(None)
        assert caplog.records[0].message == "No EVSE provided for hubject status update"

    def test_post_evse_status_with_incorrect_payload(self, caplog):
        evse = EvseFactory(status="AVAILABLE")
        evse.evse_id = "INVALID_EVSE_ID"
        HubjectService.post_eroaming_push_evse_status(evse)
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
            result = HubjectService.post_eroaming_push_evse_status(evse)
            assert result is None
            assert "Invalid OCPI status [INVALID_EVSE_ID] found" in caplog.text

    def test_post_evse_status_with_full_load_true_uses_full_load_payload(
        self, hubject_credentials
    ):
        evse = EvseFactory(status="AVAILABLE")
        get_our_credentialsrole.cache_clear()
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v21/operators/FI*CPO/status-records",
            json={"success": True},
            status=200,
            match=[
                matchers.json_params_matcher(
                    HubjectService._get_evse_status_full_load_payload().model_dump(
                        mode="json", by_alias=True
                    )
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
                HubjectService.post_eroaming_push_evse_status(evse, full_load=True)
                assert mock_get_payload.call_count == 1

    def test_get_evse_status_full_load_payload_success(
        self, operator_fi_cpo, hubject_credentials
    ):
        get_our_credentialsrole.cache_clear()
        location = LocationFactory(uid="porvoo", ocpi_master=operator_fi_cpo)
        EvseFactory(uid="Evse1", status="AVAILABLE", location=location)
        EvseFactory(uid="Evse2", status="AVAILABLE", location=location)
        result = HubjectService._get_evse_status_full_load_payload()
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
        Evse.objects.all().delete()
        result = HubjectService._get_evse_status_full_load_payload()
        assert result is None
        assert "No EVSE records found" in caplog.text


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


@pytest.mark.parametrize(
    "provider_id, expected",
    [
        (None, (None, None)),
        ("US*ABC", ("US", "ABC")),
        ("DE-XYZ", ("DE", "XYZ")),
        ("FR123", ("FR", "123")),
    ],
)
def test_decode_valid(provider_id, expected):
    assert HubjectService.decode_country_code_and_party_id(provider_id) == expected


def test_decode_invalid_raises():
    with pytest.raises(ValueError) as exc:
        HubjectService.decode_country_code_and_party_id("INVALID_FORMAT")
    assert "Invalid ProviderID format" in str(exc.value)


@pytest.mark.parametrize(
    "invalid_provider_id",
    [
        "INVALID",
        "TOO-LONG-FORMAT",
        "123",
        "",
    ],
)
def test_decode_country_code_and_party_id_raises_error_for_invalid_format(
    invalid_provider_id,
):
    with pytest.raises(ValueError, match="Invalid ProviderID format"):
        HubjectService.decode_country_code_and_party_id(invalid_provider_id)


class TestHubjectAuthorizeRemoteStart:
    hubject_service = HubjectService()

    @pytest.fixture
    def mock_remote_start_command(self):
        return ERoamingAuthorizeRemoteStart(
            session_id="f98efba4-02d8-4fa0-b810-9a9d50d2c527",
            emp_partner_session_id="MSPSession",
            evse_id=EvseID(root="DE*ABC*E123456"),
            provider_id=ProviderID(root="DE*MSP"),
            identification=Identification(
                RemoteIdentification=RemoteIdentification(
                    EvcoID=EvcoID(root="AB-VDC-C1234ABCDA")
                ),
                RFIDMifareFamilyIdentification=None,
                QRCodeIdentification=None,
                RFIDIdentification=None,
                PlugAndChargeIdentification=None,
            ),
        )

    @pytest.fixture
    def evse(self):
        e = EvseFactory(
            uid="123456",
            location=LocationFactory(
                uid="194234D1-0EDD-4B6E-8262-C85BDA16919D",
                ocpi_master=CredentialsRoleFactory(country_code="DE", party_id="ABC"),
            ),
            status="AVAILABLE",
        )

        ConnectorFactory(evse=e, uid="connector-uid-789")
        return e

    @pytest.fixture
    def start_session_webhook(self):
        return WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.START_SESSION,
            url="http://localhost/api/cpo/v2/chargepoint/start-session/",
        )

    @pytest.mark.django_db
    @responses.activate
    def test_process_remote_start_command_returns_result_true(
        self,
        evse,
        mock_remote_start_command,
        hubject_credentials,
        start_session_webhook,
    ):
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session",
            return_value=OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
            ),
        ):
            responses.add(
                responses.POST,
                "http://localhost/api/cpo/v2/chargepoint/start-session/",
                json={"data": {"result": "ACCEPTED"}},
                status=200,
            )
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        session = SessionRepository.find_session_by_auth_ref_and_token_uid(
            mock_remote_start_command.session_id.root,
            mock_remote_start_command.identification.RemoteIdentification.EvcoID.root,
        )
        assert result == ERoamingAcknowledgment(
            result=True,
            status_code=StatusCode(Code="000"),
            session_id=mock_remote_start_command.session_id,
            cpo_partner_session_id=session.uid,
            emp_partner_session_id=mock_remote_start_command.emp_partner_session_id,
        )

    @pytest.mark.django_db
    def test_process_remote_start_command_returns_result_false_when_evse_not_found(
        self, mock_remote_start_command
    ):
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result == ERoamingAcknowledgment(
            result=False,
            status_code=StatusCode(Code="603", Description="EVSE not found"),
            session_id="f98efba4-02d8-4fa0-b810-9a9d50d2c527",
            cpo_partner_session_id="",
            emp_partner_session_id="MSPSession",
        )

    @pytest.mark.django_db
    def test_process_remote_start_command_returns_result_false_when_provider_id_decode_fails(
        self, evse, mock_remote_start_command
    ):
        mock_remote_start_command.provider_id.root = "INVALID_FORMAT"

        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert isinstance(result, ERoamingAcknowledgment)
        assert result.result is False
        assert result.status_code == StatusCode(
            Code="300", Description="Invalid ProviderID format"
        )

    @pytest.mark.django_db
    def test_process_remote_start_command_returns_result_false_when_serializer_invalid(
        self, mock_remote_start_command, evse
    ):
        invalid_data = {
            "response_url": "http://example12345.com/response",
            "token": {
                "uid": "",
            },
            "location_id": "",
            "evse_uid": "",
            "connector_id": "",
            "authorization_reference": "",
        }
        with patch(
            "integrations.hubject.services.HubjectService._prepare_start_session_data",
            return_value=invalid_data,
        ):
            result = self.hubject_service.process_remote_start_command(
                mock_remote_start_command
            )

        assert result.result is False
        assert result.status_code == StatusCode(
            Code="022", Description="Invalid data for starting session"
        )

    @patch("integrations.hubject.services.HubjectService._start_session")
    @pytest.mark.django_db
    def test_process_remote_start_command_calls_start_session_when_valid(
        self, mock_start_session, mock_remote_start_command, evse
    ):
        expected_acknowledgment = Mock(spec=ERoamingAcknowledgment)
        mock_start_session.return_value = expected_acknowledgment

        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        mock_start_session.assert_called_once()
        assert result == expected_acknowledgment

    @pytest.mark.django_db
    @responses.activate
    def test_process_remote_start_command_when_evse_is_not_available(
        self,
        mock_remote_start_command,
        evse,
        hubject_credentials,
        start_session_webhook,
    ):
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session",
            return_value=OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
            ),
        ):
            responses.add(
                responses.POST,
                "http://localhost/api/cpo/v2/chargepoint/start-session/",
                json={"data": {"result": "REJECTED"}},
                status=200,
            )
        evse.status = "OUTOFORDER"
        evse.save()
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result.result is False
        assert result.status_code == StatusCode(
            Code="602", Description="EVSE is currently occupied"
        )

    @pytest.mark.django_db
    @override_settings(HOSTNAME="localhost")
    def test_prepare_start_session_data_builds_correct_structure(
        self, mock_remote_start_command
    ):
        sender_party = Party(country_code="DE", party_id="MSP")

        location_id = "194234D1-0EDD-4B6E-8262-C85BDA16919D"
        result = self.hubject_service._prepare_start_session_data(
            mock_remote_start_command, location_id, sender_party
        )

        expected_data = {
            "response_url": f"http://localhost/api/cpo/v2/chargepoint/remote_command_result/{mock_remote_start_command.session_id.root}/",
            "token": {
                "uid": "AB-VDC-C1234ABCDA",
                "contract_id": "AB-VDC-C1234ABCDA",
                "country_code": "DE",
                "party_id": "MSP",
                "type": "APP_USER",
            },
            "location_id": "194234D1-0EDD-4B6E-8262-C85BDA16919D",
            "evse_uid": "123456",
            "connector_id": "",
            "authorization_reference": "f98efba4-02d8-4fa0-b810-9a9d50d2c527",
        }
        assert result == expected_data

    @pytest.mark.django_db
    def test_prepare_start_session_data_handles_no_connectors(
        self, mock_remote_start_command, evse
    ):
        sender_party = Party(country_code="DE", party_id="MSP")
        evse.connectors.all().delete()

        result = self.hubject_service._prepare_start_session_data(
            mock_remote_start_command, evse, sender_party
        )

        assert result["connector_id"] == ""

    @override_settings(HUBJECT_OPERATOR_ID="DE*ICE")
    @pytest.mark.django_db
    def test_start_session_raises_hubject_command_error_when_response_result_is_not_accepted(
        self, mock_remote_start_command
    ):
        CredentialsRoleFactory(country_code="DE", party_id="ICE")
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session"
        ) as mock_start_session:
            mock_start_session.return_value = OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
                data={"result": "REJECTED", "timeout": 60, "message": []},
            )
            with pytest.raises(HubjectRemoteCommandError):
                self.hubject_service._start_session(
                    sender_party=Party(country_code="DE", party_id="MSP"),
                    remote_start_command=mock_remote_start_command,
                    validated_data={},
                )

    @pytest.mark.parametrize(
        "evse_status, expected_code",
        [
            (Evse.AVAILABLE, "000"),
            (Evse.BLOCKED, "501"),
            (Evse.CHARGING, "602"),
            (Evse.INOPERATIVE, "700"),
            (Evse.OUTOFORDER, "700"),
            (Evse.PLANNED, "501"),
            (Evse.REMOVED, "700"),
            (Evse.RESERVED, "601"),
            (Evse.UNKNOWN, "501"),
            ("INVALID_STATUS", "000"),
            (None, "603"),
        ],
    )
    def test_get_hubject_error_code(self, evse_status, expected_code):
        service = HubjectService()

        if evse_status is None:
            evse = None
        else:
            evse = Evse(status=evse_status)

        result = service._get_hubject_error_code(evse)
        assert result == expected_code

    @pytest.mark.django_db
    def test_process_remote_start_command_with_validation_error_return_acknowledgement_false(
        self, mock_remote_start_command, evse
    ):
        mock_remote_start_command.identification.RemoteIdentification.EvcoID.root = None
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result.result is False
        assert result.status_code == StatusCode(
            Code="022", Description="EvcoID is required for remote start command"
        )

    @pytest.mark.django_db
    def test_prepare_start_session_data_assign_hubject_session_id_for_auth_ref_when_emp_session_none(
        self, mock_remote_start_command, evse
    ):
        sender_party = Party(country_code="DE", party_id="MSP")
        mock_remote_start_command.emp_partner_session_id = None
        mock_remote_start_command.session_id.root = "hubject-session-id-123"

        result = self.hubject_service._prepare_start_session_data(
            mock_remote_start_command, evse, sender_party
        )

        assert result["authorization_reference"] == "hubject-session-id-123"

    @pytest.mark.django_db
    @override_settings(HUBJECT_OPERATOR_ID="SL*MNP")
    def test_process_remote_start_command_with_no_hubject_credentials_return_result_false(
        self, mock_remote_start_command, evse, start_session_webhook
    ):
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session",
            return_value=OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
            ),
        ):
            responses.add(
                responses.POST,
                "http://localhost/api/cpo/v2/chargepoint/start-session/",
                json={"data": {"result": "ACCEPTED"}},
                status=200,
            )
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result.result is False
        assert result.status_code == StatusCode(
            Code="021", Description="Credentials not found for Hubject"
        )

    @pytest.mark.django_db
    @responses.activate
    @override_settings(HOSTNAME="localhost")
    @pytest.mark.parametrize(
        "evse_status",
        [
            "BLOCKED",
            "INOPERATIVE",
            "OUTOFORDER",
            "PLANNED",
            "RESERVED",
            "UNKNOWN",
            "REMOVED",
        ],
    )
    def test_process_remote_start_command_with_evse_status_raises_hubject_remote_command_error(
        self,
        mock_remote_start_command,
        evse,
        evse_status,
        hubject_credentials,
    ):
        build_absolute_uri.cache_clear()
        evse.status = evse_status
        evse.save()

        url = f"http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSP{evse_status}Session/"
        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.START_SESSION,
            url=url,
        )
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session",
            return_value=OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
            ),
        ):
            responses.add(
                responses.POST, url, json={"data": {"result": "REJECTED"}}, status=200
            )
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result.result is False
        assert result.status_code.Code == "602"

    @pytest.mark.django_db
    @responses.activate
    @override_settings(HOSTNAME="localhost")
    def test_process_remote_start_for_occupied_evse_returns_acknowledgment_false(
        self,
        mock_remote_start_command,
        evse,
        hubject_credentials,
        start_session_webhook,
    ):
        with patch(
            "ocpi22.commands.services.StartCommandService.start_session",
            return_value=OCPIResponse(
                status_code=Ocpi.OK,
                http_status=status.HTTP_200_OK,
            ),
        ):
            responses.add(
                responses.POST,
                "http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
                json={"data": {"result": "REJECTED"}},
                status=200,
            )
        evse.status = "CHARGING"
        evse.save()

        OCPISessionFactory(evse=evse, status="ACTIVE")
        result = self.hubject_service.process_remote_start_command(
            mock_remote_start_command
        )

        assert result.result is False
        assert result.status_code == StatusCode(
            Code="602", Description="EVSE is currently occupied"
        )


class TestHubjectAuthorizeRemoteStop:
    hubject_service = HubjectService()

    @pytest.fixture
    def mock_data(self):
        EvseFactory(uid="12345")
        OCPISessionFactory(
            uid="OURSESSIONID",
            route_through=CredentialsRoleFactory(country_code="DE", party_id="ICE"),
            hub_session_id="f98efbae-a2d8-rfa0-b810-9a9d50d2c527",
            authorization_reference="emp_session_456",
        )

    @pytest.fixture
    def remote_stop_command(self):
        return ERoamingAuthorizeRemoteStop(
            evse_id=EvseID(root="FI*CPO*E12345"),
            session_id=SessionID(root="f98efbae-a2d8-rfa0-b810-9a9d50d2c527"),
            cpo_partner_session_id="OURSESSIONID",
            emp_partner_session_id="emp_session_456",
            provider_id=ProviderID(root="DEABC"),
        )

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        session.uid = "session_uid_789"
        return session

    @pytest.mark.django_db
    def test_process_remote_stop_command_returns_acknowledgment_false_when_evse_not_found(
        self, remote_stop_command
    ):
        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.STOP_SESSION,
            url="http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        )
        OCPISessionFactory(
            uid="OURSESSIONID", hub_session_id="f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
        )
        result = self.hubject_service.process_remote_stop_command(remote_stop_command)

        assert result.result is False
        assert result.status_code.Code == "021"
        assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
        assert result.emp_partner_session_id == "emp_session_456"

    @pytest.mark.django_db
    @responses.activate
    def test_process_remote_stop_command_returns_acknowledgment_false_when_session_not_found(
        self, remote_stop_command
    ):
        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.STOP_SESSION,
            url="http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        )
        responses.add(
            responses.POST,
            "http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        EvseFactory(uid="12345")

        result = self.hubject_service.process_remote_stop_command(remote_stop_command)

        assert result.result is False
        assert result.status_code.Code == "400"
        assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
        assert result.emp_partner_session_id == "emp_session_456"

    @pytest.mark.django_db
    def test_process_remote_stop_command_returns_acknowledgment_false_when_serializer_invalid(
        self, remote_stop_command, mock_data
    ):
        with patch(
            "ocpi22.commands.serializers.StopSessionSerializer"
        ) as mock_serializer_class:
            mock_serializer = Mock()
            mock_serializer.is_valid.return_value = False
            mock_serializer.errors = {"session_id": ["Invalid session"]}
            mock_serializer_class.return_value = mock_serializer

            result = self.hubject_service.process_remote_stop_command(
                remote_stop_command
            )

            assert result.result is False
            assert result.status_code.Code == "022"
            assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
            assert result.emp_partner_session_id == "emp_session_456"

    @pytest.mark.django_db
    def test_process_remote_stop_command_returns_acknowledgment_false_when_stop_session_rejected(
        self, remote_stop_command, mock_data
    ):
        with patch(
            "ocpi22.commands.services.StopCommandServices"
        ) as mock_service_class:
            mock_service = Mock()
            mock_response = Mock()
            mock_response.data = {"data": {"result": "REJECTED"}}
            mock_service.stop_session.return_value = mock_response
            mock_service_class.return_value = mock_service

            result = self.hubject_service.process_remote_stop_command(
                remote_stop_command
            )

            assert result.result is False
            assert result.status_code.Code == "021"
            assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
            assert result.emp_partner_session_id == "emp_session_456"

    @pytest.mark.django_db
    def test_process_remote_stop_command_returns_acknowledgment_false_when_stop_session_data_none(
        self, remote_stop_command, mock_data
    ):
        with patch(
            "ocpi22.commands.services.StopCommandServices"
        ) as mock_service_class:
            mock_service = Mock()
            mock_response = Mock()
            mock_response.data = {"data": None}
            mock_service.stop_session.return_value = mock_response
            mock_service_class.return_value = mock_service

            result = self.hubject_service.process_remote_stop_command(
                remote_stop_command
            )

            assert result.result is False
            assert result.status_code.Code == "021"
            assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
            assert result.emp_partner_session_id == "emp_session_456"

    @pytest.mark.django_db
    @responses.activate
    def test_process_remote_stop_command_returns_success_acknowledgment_when_stop_session_accepted(
        self, remote_stop_command, mock_data
    ):
        responses.add(
            responses.POST,
            "http://localhost/api/cpo/v2/chargepoint/remote_command_result/emp_session_456/",
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.STOP_SESSION,
            url="http://localhost/api/cpo/v2/chargepoint/remote_command_result/emp_session_456/",
        )
        result = self.hubject_service.process_remote_stop_command(remote_stop_command)

        assert result.result is True
        assert result.status_code.Code == "000"
        assert result.session_id.root == "f98efbae-a2d8-rfa0-b810-9a9d50d2c527"
        assert result.cpo_partner_session_id == "OURSESSIONID"
        assert result.emp_partner_session_id == "emp_session_456"

    def test_validate_command_response_raises_hubject_error_when_session_not_found(
        self,
    ):
        response_data = {"data": {"result": "UNKNOWN_SESSION"}}
        with pytest.raises(HubjectRemoteCommandError) as exc_info:
            self.hubject_service._validate_command_response(response_data)

        assert exc_info.value.args[0] == "Session not found"
        assert exc_info.value.error_code == "400"


@pytest.fixture
def validation_error_response():
    return {
        "message": "Validation failed",
        "validationErrors": [
            {
                "fieldReference": "OperatorEvseData.EvseDataRecord[0].Address.Street",
                "errorMessage": "Street is required",
            },
            {
                "fieldReference": "OperatorEvseData.EvseDataRecord[1].GeoCoordinates.Latitude",
                "errorMessage": "Invalid latitude format",
            },
        ],
    }


class TestParseHubjectValidationErrors:
    def test_parse_validation_errors_successfully(
        self, validation_error_response, sample_evse_data_payload
    ):
        result = HubjectService.parse_hubject_validation_errors(
            validation_error_response, sample_evse_data_payload
        )

        assert result["message"] == "Validation failed"
        assert result["error_count"] == 2
        assert result["status_code"] == 400
        assert len(result["errors"]) == 2
        assert "Street is required" in result["errors"][0]
        assert "Invalid latitude format" in result["errors"][1]

    def test_field_summary_aggregation(
        self, validation_error_response, sample_evse_data_payload
    ):
        result = HubjectService.parse_hubject_validation_errors(
            validation_error_response, sample_evse_data_payload
        )

        assert "Address.Street" in result["field_summary"]
        assert result["field_summary"]["Address.Street"] == 1
        assert "GeoCoordinates.Latitude" in result["field_summary"]
        assert result["field_summary"]["GeoCoordinates.Latitude"] == 1

    def test_evse_index_extraction(
        self, validation_error_response, sample_evse_data_payload
    ):
        result = HubjectService.parse_hubject_validation_errors(
            validation_error_response, sample_evse_data_payload
        )

        assert "DE*BER*EMNOEVSEUID" in result["errors"][0]
        assert "DE*BER*ESECONDUID" in result["errors"][1]

    def test_missing_field_reference(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "errorMessage": "Some error without field reference",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert "unknown" in result["errors"][0]
        assert result["error_count"] == 1

    def test_missing_error_message(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "fieldReference": "OperatorEvseData.EvseDataRecord[0].Address.Street",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert "No error message" in result["errors"][0]

    def test_invalid_index_in_field_reference(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "fieldReference": "OperatorEvseData.EvseDataRecord[999].Address.Street",
                    "errorMessage": "Invalid index",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert "Unknown" in result["errors"][0]

    def test_unexpected_field_reference_format(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "fieldReference": "OperatorEvseData.SomeField",
                    "errorMessage": "Invalid field",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert result["error_count"] == 1
        assert "Unknown" in result["errors"][0]

    def test_empty_validation_errors(self, sample_evse_data_payload):
        response = {
            "message": "No validation errors",
            "validationErrors": [],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert result["error_count"] == 0
        assert len(result["errors"]) == 0
        assert result["field_summary"] == {}

    def test_missing_validation_errors_key(self, sample_evse_data_payload):
        response = {
            "message": "Some error",
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert result["error_count"] == 0
        assert result["message"] == "Some error"

    def test_missing_message_key(self, sample_evse_data_payload):
        response = {
            "validationErrors": [],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert result["message"] == "Unknown error"

    def test_field_reference_with_bracket_notation(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "fieldReference": "OperatorEvseData.EvseDataRecord[0].Address.Street",
                    "errorMessage": "Invalid",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert "Address.Street" in result["field_summary"]

    def test_field_reference_without_bracket_notation(self, sample_evse_data_payload):
        response = {
            "message": "Validation failed",
            "validationErrors": [
                {
                    "fieldReference": "OperatorEvseData.OperatorName",
                    "errorMessage": "Invalid",
                }
            ],
        }

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert "OperatorName" in result["field_summary"]

    def test_exception_handling(self, sample_evse_data_payload):
        response = "invalid_json_string"

        result = HubjectService.parse_hubject_validation_errors(
            response, sample_evse_data_payload
        )

        assert result["message"] == "Failed to parse validation errors"
        assert result["error_count"] == 1
        assert result["status_code"] == 500
        assert result["errors"] == "invalid_json_string"

    def test_none_response(self, sample_evse_data_payload):
        result = HubjectService.parse_hubject_validation_errors(
            None, sample_evse_data_payload
        )

        assert result["message"] == "Failed to parse validation errors"
        assert result["status_code"] == 500
