import doctest
from datetime import datetime, timezone, timedelta
from unittest import mock
from unittest.mock import patch

import pytest
import pytz
import time_machine
from django.core.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from integrations.hubject.schemas import (
    Plug,
    PowerType,
    ChargingFacility,
    AuthenticationMode,
    ActionType,
    ERoamingPushEvseData,
    PaymentOption,
    ValueAddedService,
    DynamicInfoAvailable,
    CalibrationLawDataAvailability,
    Accessibility,
    AccessibilityLocation,
    HubjectPriceComponent,
    ProviderIDAsterisk,
    HubjectDefaultTariff,
    On,
    OpeningTimes,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from ocpi22.choices import OCPICapability, WEEKDAY_CHOICES
from ocpi22.cpo.schemas import RegularHours
from ocpi22.cpo.api import applying_tariff_element
from ocpi22.models.location import Connector
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    LocationFactory,
    EvseFactory,
    OCPISessionFactory,
    SolidTariffFactory,
)
from integrations.hubject.schemas import EvseStatus as OICPEvseStatus


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("integrations.solid_to_hubject_converter"))
    return tests


def get_timezone_offset(timezone: str) -> str:
    try:
        tz = datetime.now(pytz.timezone(timezone))
        return f"{tz.strftime('UTC%z')[:6]}:{tz.strftime('UTC%z')[6:]}"
    except pytz.exceptions.UnknownTimeZoneError:
        raise ValidationError(f"Unknown timezone: {timezone}")


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


class TestMappings:
    _ocpi_to_oicp_converter = SolidToHubjectConverter()

    def test_map_connector_std_choices_to_plug_unknown(self):
        with pytest.raises(ValidationError):
            TestMappings._ocpi_to_oicp_converter.get_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        mapped_plugs = TestMappings._ocpi_to_oicp_converter.get_distinct_plugs(
            connectors
        )

        assert (
            Plug.CHAdeMO in mapped_plugs
        ), "The CHAdeMO plug is not in the mapped plugs."
        assert (
            Plug.Type_2_Outlet in mapped_plugs
        ), "The Type 2 Outlet plug is not in the mapped plugs."

    def test_map_power_type_choices_221_to_power_type_unknown(self):
        with pytest.raises(ValidationError):
            TestMappings._ocpi_to_oicp_converter.get_power_type("UNKNOWN_POWER_TYPE")

    def test_get_all_charging_facilities_from_connectors(self):
        connectors = [
            Connector(
                power_type="AC_1_PHASE",
                max_voltage=230,
                max_amperage=16,
                max_electric_power=37000,
            ),
            Connector(
                power_type="DC",
                max_voltage=401,
                max_amperage=45,
                max_electric_power=50000,
            ),
        ]
        expected_facilities = [
            ChargingFacility(
                PowerType=PowerType.AC_1_PHASE, Voltage=230, Amperage=16, Power=37
            ),
            ChargingFacility(
                PowerType=PowerType.DC, Voltage=401, Amperage=45, Power=50
            ),
        ]
        assert (
            self._ocpi_to_oicp_converter.get_charging_facilities(connectors)
            == expected_facilities
        )

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapability.RFID_READER, OCPICapability.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        assert (
            self._ocpi_to_oicp_converter.get_authentication_modes_list(capabilities)
            == authentication_modes
        )

    def test_accessibility_locations_when_parking_type_none(self):
        assert (
            TestMappings._ocpi_to_oicp_converter.get_accessibility_locations(None)
            is None
        )

    @pytest.mark.django_db
    def test_map_location_to_eroaming_push_evse_data(self, helsinki2_location):
        evse_id = helsinki2_location.evses.first().evse_id
        expected_data = self.expected_helsinki_eroaming_push_evse_data(
            evse_id, helsinki2_location.uid
        )

        helsinki_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=self._ocpi_to_oicp_converter.convert_to_operator_evse_data(
                helsinki2_location
            ),
        )
        assert helsinki2_location.evses.count() == 1
        assert (
            helsinki_hubject_evse_data.model_dump() == expected_data
        ), "The mapped OCPI Location data does not match the expected OICP data."

    @pytest.mark.django_db
    def test_convert_to_eroaming_with_only_required_data(self, berlin2_location):
        evse_id = berlin2_location.evses.first().evse_id
        berlin_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=TestMappings._ocpi_to_oicp_converter.convert_to_operator_evse_data(
                berlin2_location
            ),
        )

        assert berlin2_location.evses.count() == 1
        assert (
            berlin_hubject_evse_data.model_dump()
            == self.expected_berlin_eroaming_push_evse_data(
                evse_id, berlin2_location.uid
            )
        ), "The mapped OCPI Location data does not match the expected OICP data."

    def test_french_address(self):
        french_street_addr = "36 rue Pierre De Coubertin"
        french_country_code = "FRA"
        street, house_num = self._ocpi_to_oicp_converter.get_address_components(
            french_street_addr, french_country_code
        )

        expected_street_addr = "rue Pierre De Coubertin"
        expected_house_num = "36"
        assert street == expected_street_addr
        assert house_num == expected_house_num

    @pytest.mark.parametrize(
        "address, country, expected",
        [
            pytest.param(
                "Weteringstraat 34-1",
                "NLD",
                ("Weteringstraat", "34-1"),
                id="netherlands-street-house",
            ),
            pytest.param(
                "Weberstr. 2", "DEU", ("Weberstr.", "2"), id="germany-street-house"
            ),
            pytest.param(
                "Kandintie 4E", "FIN", ("Kandintie", "4E"), id="finland-street-house"
            ),
            pytest.param(
                "23 Rue de Grenelle",
                "FRA",
                ("Rue de Grenelle", "23"),
                id="france-house-street",
            ),
            pytest.param(
                "23 avenue de la grande armée",
                "FRA",
                ("avenue de la grande armée", "23"),
                id="france-lower-case-with-special-characters",
            ),
            pytest.param(
                "23, Boulevard Saint-Jacques",
                "FRA",
                ("Boulevard Saint-Jacques", "23"),
                id="france-address-with-comma-and-dash",
            ),
            pytest.param(
                "Invalid Address", "NLD", ("-", "-"), id="netherlands-invalid"
            ),
            pytest.param(
                "Just A Street", "NLD", ("-", "-"), id="only-street-no-number"
            ),
            pytest.param("5", "FRA", ("-", "-"), id="only-house-number"),
            pytest.param(
                "12 Unknown Street", "USA", ("-", "-"), id="invalid-format-usa"
            ),
            pytest.param("", "NLD", ("-", "-"), id="empty-address-nld"),
            pytest.param("", "FRA", ("-", "-"), id="empty-address-fra"),
        ],
    )
    def test_get_address_components(self, address, country, expected):
        result = self._ocpi_to_oicp_converter.get_address_components(address, country)
        assert result == expected

    def test_invalid_address(self):
        invalid_street_addr = "Coubertin"
        invalid_country_code = "FRA"
        street, house_num = self._ocpi_to_oicp_converter.get_address_components(
            invalid_street_addr, invalid_country_code
        )

        expected_value = "-"
        assert street == expected_value
        assert house_num == expected_value

    def test_invalid_timzone(self):
        with pytest.raises(ValidationError):
            self._ocpi_to_oicp_converter.get_timezone("Unknown")

    @pytest.mark.django_db
    def test_maximum_power_with_multiple_connectors(
        self,
        connector_max_electric_power_10kw,
        connector_max_electric_power_15kw,
        connector_max_electric_power_5kw,
    ):
        max_power = self._ocpi_to_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 15

    @pytest.mark.django_db
    def test_maximum_power_with_no_connectors(self):
        Connector.objects.all().delete()
        max_power = self._ocpi_to_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 0

    @pytest.mark.django_db
    def test_maximum_power_when_connector_max_electric_power_none(
        self, connector_max_electric_power_none
    ):
        max_power = self._ocpi_to_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 0

    @pytest.mark.django_db
    def test_maximum_power_when_connector_max_electric_power_none_and_connector_max_electric_power_10kw(
        self, connector_max_electric_power_10kw, connector_max_electric_power_none
    ):
        max_power = self._ocpi_to_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 10

    def test_get_pricing_product_id(self):
        solid_tariff_id = "SD123"
        ocpi_tariff_uid = "TARIFF456"
        result = self._ocpi_to_oicp_converter.get_pricing_product_id(
            solid_tariff_id, ocpi_tariff_uid
        )
        expected = "TARIFF456*SD123"
        assert result == expected, f"Expected {expected}, but got {result}"

    @pytest.mark.django_db
    def test_convert_to_pricing_product_data_records_success(
        self,
        smp1_solid_tariff_with_all_records,
        pricing_product_data_record_successful_result,
    ):
        pricing_product_data_records = (
            self._ocpi_to_oicp_converter.convert_to_pricing_product_data_records(
                smp1_solid_tariff_with_all_records
            )
        )
        assert (
            pricing_product_data_records
            == pricing_product_data_record_successful_result
        )

    @pytest.mark.django_db
    def test_convert_to_pricing_product_data_records_when_prices_are_none(
        self,
        smp1_solid_tariff_with_none_prices,
        pricing_product_data_record_successful_result,
    ):
        with pytest.raises(
            ValidationError,
            match=f"['SolidTariff {smp1_solid_tariff_with_none_prices.external_id} is a free tariff without any price defined.']",
        ):
            self._ocpi_to_oicp_converter.convert_to_pricing_product_data_records(
                smp1_solid_tariff_with_none_prices
            )

    @pytest.mark.django_db
    def test_get_provider_ids_for_solid_tariffs_with_msp(
        self, smp1_solid_tariff_with_all_records
    ):
        result = self._ocpi_to_oicp_converter.get_provider_ids(
            [smp1_solid_tariff_with_all_records]
        )
        assert result == ProviderIDAsterisk(root="DE*ICE")

    @pytest.mark.django_db
    def test_get_provider_ids_for_solid_tariffs_without_msp(
        self, smp1_solid_tariff_without_msp
    ):
        result = self._ocpi_to_oicp_converter.get_provider_ids(
            [smp1_solid_tariff_without_msp]
        )
        assert result == ProviderIDAsterisk(root="*")

    @pytest.mark.django_db
    def test_convert_to_pricing_product_data_success(
        self, smp1_solid_tariff_with_all_records, pricing_product_data_successful_result
    ):
        default_tariff = HubjectDefaultTariff(
            currency="EUR", price=0.3, price_component=HubjectPriceComponent.HOUR
        )
        result = self._ocpi_to_oicp_converter.convert_to_pricing_product_data(
            [smp1_solid_tariff_with_all_records],
            default_tariff,
            "FI*CPO",
            "Smappee eRoam CPO",
        )
        assert result == pricing_product_data_successful_result

    def expected_helsinki_eroaming_push_evse_data(self, evse_id: str, location_id: str):
        return {
            "ActionType": ActionType.insert,
            "OperatorEvseData": {
                "OperatorID": "DE*SMP",
                "OperatorName": "Smappee Pvt Ltd",
                "EvseDataRecord": [
                    {
                        "Accessibility": Accessibility.Free_publicly_accessible,
                        "AccessibilityLocation": AccessibilityLocation.OnStreet,
                        "AdditionalInfo": None,
                        "Address": {
                            "City": "Helsinki",
                            "Country": "FIN",
                            "Floor": None,
                            "HouseNum": "1",
                            "ParkingFacility": True,
                            "ParkingSpot": None,
                            "PostalCode": "00100",
                            "Region": None,
                            "Street": "Mannerheimintie",
                            "TimeZone": get_timezone_offset("Europe/Helsinki"),
                        },
                        "AuthenticationModes": [AuthenticationMode.NFC_RFID_Classic],
                        "CalibrationLawDataAvailability": CalibrationLawDataAvailability.Not_Available,
                        "ChargingFacilities": [
                            {
                                "Amperage": 16,
                                "ChargingModes": None,
                                "Power": 37,
                                "PowerType": PowerType.DC,
                                "Voltage": 230,
                            }
                        ],
                        "ChargingPoolID": None,
                        "ChargingStationImage": None,
                        "ChargingStationLocationReference": None,
                        "ChargingStationNames": [
                            {"lang": "en", "value": "Helsinki Supercharger"}
                        ],
                        "ClearinghouseID": None,
                        "ChargingStationId": location_id,
                        "DynamicInfoAvailable": DynamicInfoAvailable.true,
                        "DynamicPowerLevel": None,
                        "EnergySource": None,
                        "EnvironmentalImpact": None,
                        "EvseID": evse_id,
                        "GeoChargingPointEntrance": {
                            "DecimalDegree": {
                                "Latitude": "60.169500",
                                "Longitude": "24.935400",
                            },
                            "DegreeMinuteSeconds": None,
                            "Google": None,
                        },
                        "GeoCoordinates": {
                            "DecimalDegree": {
                                "Latitude": "60.169500",
                                "Longitude": "24.935400",
                            },
                            "DegreeMinuteSeconds": None,
                            "Google": None,
                        },
                        "HardwareManufacturer": None,
                        "HotlinePhoneNumber": "+3256380211",
                        "HubOperatorID": None,
                        "IsHubjectCompatible": True,
                        "IsOpen24Hours": True,
                        "MaxCapacity": None,
                        "OpeningTimes": None,
                        "PaymentOptions": [PaymentOption.Contract],
                        "Plugs": [Plug.Type_2_Outlet],
                        "RenewableEnergy": False,
                        "SubOperatorName": None,
                        "ValueAddedServices": [ValueAddedService.Reservation],
                        "deltaType": None,
                        "lastUpdate": datetime(
                            2024, 9, 22, 12, 30, 30, 0, tzinfo=timezone.utc
                        ),
                    }
                ],
            },
        }

    def expected_berlin_eroaming_push_evse_data(self, evse_id: str, location_id: str):
        return {
            "ActionType": ActionType.insert,
            "OperatorEvseData": {
                "OperatorID": "DE*SMP",
                "OperatorName": "Smappee Pvt Ltd",
                "EvseDataRecord": [
                    {
                        "Accessibility": Accessibility.Free_publicly_accessible,
                        "AccessibilityLocation": AccessibilityLocation.OnStreet,
                        "AdditionalInfo": None,
                        "Address": {
                            "City": "Wallenhorst",
                            "Country": "DEU",
                            "Floor": None,
                            "HouseNum": "4",
                            "ParkingFacility": True,
                            "ParkingSpot": None,
                            "PostalCode": "",
                            "Region": None,
                            "Street": "Ansgarstr.",
                            "TimeZone": get_timezone_offset("Europe/Berlin"),
                        },
                        "AuthenticationModes": [
                            AuthenticationMode.No_Authentication_Required
                        ],
                        "CalibrationLawDataAvailability": CalibrationLawDataAvailability.Local,
                        "ChargingFacilities": [
                            {
                                "Amperage": 16,
                                "ChargingModes": None,
                                "Power": 12,
                                "PowerType": PowerType.AC_3_PHASE,
                                "Voltage": 0,
                            }
                        ],
                        "ChargingPoolID": None,
                        "ChargingStationId": location_id,
                        "ChargingStationImage": None,
                        "ChargingStationLocationReference": None,
                        "ChargingStationNames": [
                            {"lang": "en", "value": "Berlin Location"}
                        ],
                        "ClearinghouseID": None,
                        "DynamicInfoAvailable": DynamicInfoAvailable.true,
                        "DynamicPowerLevel": None,
                        "EnergySource": None,
                        "EnvironmentalImpact": None,
                        "EvseID": evse_id,
                        "GeoChargingPointEntrance": {
                            "DecimalDegree": {
                                "Latitude": "0.000000",
                                "Longitude": "0.000000",
                            },
                            "DegreeMinuteSeconds": None,
                            "Google": None,
                        },
                        "GeoCoordinates": {
                            "DecimalDegree": {
                                "Latitude": "0.000000",
                                "Longitude": "0.000000",
                            },
                            "DegreeMinuteSeconds": None,
                            "Google": None,
                        },
                        "HardwareManufacturer": None,
                        "HotlinePhoneNumber": "+3256380211",
                        "HubOperatorID": None,
                        "IsHubjectCompatible": True,
                        "IsOpen24Hours": True,
                        "MaxCapacity": None,
                        "OpeningTimes": None,
                        "PaymentOptions": [PaymentOption.Contract],
                        "Plugs": [Plug.Type_2_Outlet],
                        "RenewableEnergy": False,
                        "SubOperatorName": None,
                        "ValueAddedServices": [ValueAddedService.None_],
                        "deltaType": None,
                        "lastUpdate": datetime(
                            2024, 9, 22, 12, 30, 30, 0, tzinfo=timezone.utc
                        ),
                    }
                ],
            },
        }

    @pytest.mark.parametrize(
        "ocpi_status,expected_oicp_status",
        [
            ("AVAILABLE", OICPEvseStatus.Available),
            ("BLOCKED", OICPEvseStatus.Occupied),
            ("CHARGING", OICPEvseStatus.Occupied),
            ("INOPERATIVE", OICPEvseStatus.OutOfService),
            ("OUTOFORDER", OICPEvseStatus.OutOfService),
            ("PLANNED", OICPEvseStatus.Occupied),
            ("REMOVED", OICPEvseStatus.OutOfService),
            ("RESERVED", OICPEvseStatus.Reserved),
            ("UNKNOWN", OICPEvseStatus.Unknown),
        ],
    )
    def test_convert_ocpi_evse_status_successfully_returns_expected_oicp_status(
        self, ocpi_status, expected_oicp_status
    ):
        result = self._ocpi_to_oicp_converter.convert_ocpi_evse_status(ocpi_status)
        assert result == expected_oicp_status

    @pytest.mark.parametrize(
        "ocpi_status",
        [
            "available",
            "Available",
            "AVAILABLE",
        ],
    )
    def test_convert_ocpi_evse_status_case_insensitive_returns_expected_oicp_status(
        self, ocpi_status
    ):
        result = self._ocpi_to_oicp_converter.convert_ocpi_evse_status(ocpi_status)
        assert result == OICPEvseStatus.Available

    @pytest.mark.parametrize(
        "invalid_status",
        [
            "UNKNOWN_STATUS",
            "INVALID",
            "",
            "RANDOM_STRING",
        ],
    )
    def test_convert_ocpi_evse_status_invalid_status_returns_unknown_status(
        self, invalid_status
    ):
        with pytest.raises(
            ValueError, match=f"Invalid OCPI status \\[{invalid_status}\\] found"
        ):
            self._ocpi_to_oicp_converter.convert_ocpi_evse_status(invalid_status)


class TestConvertOCPICDRToERoamingCDR:
    _ocpi_to_oicp_converter = SolidToHubjectConverter()

    @pytest.mark.django_db
    def test_conversion_with_valid_data_returns_correct_eroaming_cdr(
        self, ocpi_cdr, expected_eroaming_cdr
    ):
        eroaming = (
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )
        )
        assert eroaming.model_dump(by_alias=True, mode="json") == expected_eroaming_cdr

    @pytest.mark.django_db
    def test_total_energy_exceeds_1000_raises_validation_error(self, ocpi_cdr):
        ocpi_cdr.total_energy = 1001

        with pytest.raises(PydanticValidationError):
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )

    @pytest.mark.django_db
    def test_start_time_gt_end_time_raises_validation_error(self, ocpi_cdr):
        ocpi_cdr.start_date_time = datetime.now(pytz.utc)
        ocpi_cdr.end_date_time = datetime.now(pytz.utc) - timedelta(hours=1)

        with pytest.raises(
            PydanticValidationError,
        ):
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )

    @pytest.mark.django_db
    def test_end_time_in_future_raises_validation_error(self, ocpi_cdr):
        ocpi_cdr.end_date_time = datetime.now(pytz.utc) + timedelta(hours=1)

        with pytest.raises(PydanticValidationError):
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )

    @pytest.mark.django_db
    def test_meter_value_end_lt_meter_value_start_raises_validation_error(
        self, ocpi_cdr
    ):
        with patch("ocpi22.models.session.Session.objects.filter") as mock_filter:
            mock_session = OCPISessionFactory()
            mock_session.start_kwh = 10
            mock_session.stop_kwh = 5
            mock_filter.return_value.first.return_value = mock_session

            with pytest.raises(
                PydanticValidationError,
            ):
                self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                    ocpi_cdr
                )

    @pytest.mark.django_db
    def test_negative_energy_raises_validation_error(self, ocpi_cdr):
        ocpi_cdr.total_energy = -1

        with pytest.raises(PydanticValidationError):
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )

    @pytest.mark.django_db
    def test_non_existing_session_raises_validation_error(self, ocpi_cdr):
        Session.objects.filter(uid__iexact=ocpi_cdr.session_id).delete()

        with pytest.raises(
            ValidationError, match=f"No session found for ID {ocpi_cdr.session_id}"
        ):
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )

    @pytest.mark.django_db
    def test_external_calibration_without_signed_values_raises_validation_error(
        self, ocpi_cdr, session_for_cdr
    ):
        with mock.patch("ocpi22.models.session.Session.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = session_for_cdr

            with mock.patch.object(
                self._ocpi_to_oicp_converter, "_convert_to_evse_data_record"
            ) as mock_convert_to_evse_data_record:
                mock_evse_data = mock.MagicMock()
                mock_evse_data.CalibrationLawDataAvailability = (
                    CalibrationLawDataAvailability.External
                )
                mock_convert_to_evse_data_record.return_value = mock_evse_data

                with pytest.raises(
                    ValidationError,
                    match="SignedMeteringValues must be provided when CalibrationLawDataAvailability is External.",
                ):
                    self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                        ocpi_cdr
                    )

    @pytest.mark.django_db
    def test_eroaming_cdr_without_solid_tariff_returns_cdr_with_partner_product_id_none(
        self, ocpi_cdr
    ):
        eroaming_cdr = (
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )
        )
        assert (
            eroaming_cdr.partner_product_id is None
        ), "PartnerProductID should be None when SolidTariff is not provided."

    @pytest.mark.django_db
    def test_eroaming_cdr_with_solid_tariff_returns_cdr_with_correct_partner_product_id(
        self, ocpi_cdr
    ):
        tariff = applying_tariff_element(ocpi_cdr.session).tariff
        solid_tariff = SolidTariffFactory(
            external_id="SD1",
            ocpi_tariff=tariff,
            msp=ocpi_cdr.billed_to,
            operator=ocpi_cdr.ocpi_master,
        )
        eroaming_cdr = (
            self._ocpi_to_oicp_converter.convert_cdr_to_eroaming_charging_detail_record(
                ocpi_cdr
            )
        )
        assert (
            eroaming_cdr.partner_product_id.root
            == self._ocpi_to_oicp_converter.get_pricing_product_id(
                external_id=solid_tariff.external_id,
                ocpi_tariff_uid=solid_tariff.ocpi_tariff.uid,
            )
        )


@pytest.fixture
def weekday_regular_hours():
    return [
        RegularHours(weekday=weekday, period_begin="00:00", period_end="00:00")
        for weekday in range(1, 6)
    ]


@pytest.fixture
def weekend_regular_hours():
    return [
        RegularHours(weekday=weekday, period_begin="00:00", period_end="00:00")
        for weekday in range(6, 8)
    ]


@pytest.fixture
def everyday_regular_hours():
    return [
        RegularHours(weekday=weekday, period_begin="00:00", period_end="00:00")
        for weekday in range(1, 8)
    ]


@pytest.fixture
def monday_to_wednesday_regular_hours():
    return [
        RegularHours(weekday=1, period_begin="00:00", period_end="00:00"),
        RegularHours(weekday=2, period_begin="10:30", period_end="17:20"),
        RegularHours(weekday=3, period_begin="09:15", period_end="16:00"),
    ]


@pytest.fixture
def monday_regular_hours():
    return [
        RegularHours(weekday=1, period_begin="00:00", period_end="06:00"),
        RegularHours(weekday=1, period_begin="06:30", period_end="12:20"),
        RegularHours(weekday=1, period_begin="12:30", period_end="20:00"),
    ]


def test_get_weekday_from_number():
    assert WEEKDAY_CHOICES.from_number(1) == WEEKDAY_CHOICES.Monday
    assert WEEKDAY_CHOICES.from_number(2) == WEEKDAY_CHOICES.Tuesday
    assert WEEKDAY_CHOICES.from_number(3) == WEEKDAY_CHOICES.Wednesday
    assert WEEKDAY_CHOICES.from_number(4) == WEEKDAY_CHOICES.Thursday
    assert WEEKDAY_CHOICES.from_number(5) == WEEKDAY_CHOICES.Friday
    assert WEEKDAY_CHOICES.from_number(6) == WEEKDAY_CHOICES.Saturday
    assert WEEKDAY_CHOICES.from_number(7) == WEEKDAY_CHOICES.Sunday
    assert WEEKDAY_CHOICES.from_number(8) is None


@pytest.mark.parametrize(
    "regular_hours_fixture, expected_on, expected_count, description",
    [
        ("weekday_regular_hours", On.Workdays, 1, "weekdays"),
        ("weekend_regular_hours", On.Weekend, 1, "weekends"),
        ("everyday_regular_hours", On.Everyday, 1, "everyday"),
    ],
)
def test_map_regular_hours_to_opening_times(
    regular_hours_fixture, expected_on, expected_count, description, request
):
    regular_hours = request.getfixturevalue(regular_hours_fixture)
    opening_times: list[OpeningTimes] = (
        TestMappings._ocpi_to_oicp_converter.map_regular_hours_to_opening_times(
            regular_hours
        )
    )

    assert (
        len(opening_times) == expected_count
    ), f"There should be just {expected_count} opening times for {description}."
    assert opening_times[0].on == expected_on
    assert (
        opening_times[0].Period[0].begin == "00:00"
    ), "Period begin should be '00:00'."
    assert opening_times[0].Period[0].end == "00:00", "Period end should be '00:00'."


def test_map_regular_hours_to_opening_times_from_monday_to_wednesday_returns_3_opening_times(
    monday_to_wednesday_regular_hours,
):
    opening_times: list[OpeningTimes] = (
        TestMappings._ocpi_to_oicp_converter.map_regular_hours_to_opening_times(
            monday_to_wednesday_regular_hours
        )
    )

    expected_times = {
        On.Monday: {"begin": "00:00", "end": "00:00"},
        On.Tuesday: {"begin": "10:30", "end": "17:20"},
        On.Wednesday: {"begin": "09:15", "end": "16:00"},
    }

    assert (
        len(opening_times) == 3
    ), "There should be just 3 opening times for Monday to Wednesday."

    for ot in opening_times:
        assert ot.on in expected_times, f"{ot.on} is not in the expected opening times."
        expected_begin = expected_times[ot.on]["begin"]
        expected_end = expected_times[ot.on]["end"]

        assert (
            ot.Period[0].begin == expected_begin
        ), f"Period begin for {ot.on} should be '{expected_begin}'."
        assert (
            ot.Period[0].end == expected_end
        ), f"Period end for {ot.on} should be '{expected_end}'."

        del expected_times[ot.on]

    assert not expected_times, "Not all expected opening times were found."


def test_map_regular_hours_with_multiple_periods_for_monday_returns_one_opening_time(
    monday_regular_hours,
):
    opening_times: list[OpeningTimes] = (
        TestMappings._ocpi_to_oicp_converter.map_regular_hours_to_opening_times(
            monday_regular_hours
        )
    )

    assert len(opening_times) == 1, "There should be one opening time entry for Monday"
    assert opening_times[0].on == On.Monday, "The opening time should be for Monday"

    periods = opening_times[0].Period
    assert len(periods) == 3, "There should be three periods for Monday"

    expected_periods = [
        {"begin": "00:00", "end": "06:00"},
        {"begin": "06:30", "end": "12:20"},
        {"begin": "12:30", "end": "20:00"},
    ]

    for i, period in enumerate(periods):
        expected = expected_periods[i]
        assert (
            period.begin == expected["begin"]
        ), f"Period {i} begin should be '{expected['begin']}'"
        assert (
            period.end == expected["end"]
        ), f"Period {i} end should be '{expected['end']}'"
