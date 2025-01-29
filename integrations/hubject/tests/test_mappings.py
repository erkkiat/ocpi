import doctest
from datetime import datetime, timezone

import pytest
import pytz
import time_machine
from django.core.exceptions import ValidationError

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
)
from integrations.hubject_to_ocpi_converter import HubjectToOCPIConverter
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Connector
from ocpi22.tests.factories import LocationFactory, EvseFactory


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("integrations.solid_to_hubject_converter"))
    tests.addTests(doctest.DocTestSuite("integrations.hubject_to_ocpi_converter"))
    return tests


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
    _ocpi_2_oicp_converter = SolidToHubjectConverter()
    _oicp_to_ocpi_converter = HubjectToOCPIConverter()

    def test_map_connector_std_choices_to_plug_unknown(self):
        with pytest.raises(ValidationError):
            TestMappings._ocpi_2_oicp_converter.get_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        mapped_plugs = TestMappings._ocpi_2_oicp_converter.get_distinct_plugs(
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
            TestMappings._ocpi_2_oicp_converter.get_power_type("UNKNOWN_POWER_TYPE")

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
            self._ocpi_2_oicp_converter.get_charging_facilities(connectors)
            == expected_facilities
        )

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        assert (
            self._ocpi_2_oicp_converter.get_authentication_modes_list(capabilities)
            == authentication_modes
        )

    def test_accessibility_locations_when_parking_type_none(self):
        assert (
            TestMappings._ocpi_2_oicp_converter.get_accessibility_locations(None)
            is None
        )

    @pytest.mark.django_db
    def test_map_location_to_eroaming_push_evse_data(self, helsinki2_location):
        evse_id = helsinki2_location.evses.first().evse_id
        expected_data = self.expected_helsinki_eroaming_push_evse_data(evse_id)

        helsinki_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=self._ocpi_2_oicp_converter.convert_to_operator_evse_data(
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
            OperatorEvseData=TestMappings._ocpi_2_oicp_converter.convert_to_operator_evse_data(
                berlin2_location
            ),
        )

        assert berlin2_location.evses.count() == 1
        assert (
            berlin_hubject_evse_data.model_dump()
            == self.expected_berlin_eroaming_push_evse_data(evse_id)
        ), "The mapped OCPI Location data does not match the expected OICP data."

    def test_french_address(self):
        french_street_addr = "36 rue Pierre De Coubertin"
        french_country_code = "FRA"
        street, house_num = self._ocpi_2_oicp_converter.get_address_components(
            french_street_addr, french_country_code
        )

        expected_street_addr = "rue Pierre De Coubertin"
        expected_house_num = "36"
        assert street == expected_street_addr
        assert house_num == expected_house_num

    def test_invalid_address(self):
        invalid_street_addr = "Coubertin"
        invalid_country_code = "FRA"
        street, house_num = self._ocpi_2_oicp_converter.get_address_components(
            invalid_street_addr, invalid_country_code
        )

        print(street, house_num)
        expected_value = "-"
        assert street == expected_value
        assert house_num == expected_value

    def test_invalid_timzone(self):
        with pytest.raises(ValidationError):
            self._ocpi_2_oicp_converter.get_timezone("Unknown")

    @pytest.mark.django_db
    def test_maximum_power_with_multiple_connectors(
        self,
        connector_max_electric_power_10kw,
        connector_max_electric_power_15kw,
        connector_max_electric_power_5kw,
    ):
        max_power = self._ocpi_2_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 15

    @pytest.mark.django_db
    def test_maximum_power_with_no_connectors(self):
        Connector.objects.all().delete()
        max_power = self._ocpi_2_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 0

    @pytest.mark.django_db
    def test_maximum_power_when_connector_max_electric_power_none(
        self, connector_max_electric_power_none
    ):
        max_power = self._ocpi_2_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 0

    @pytest.mark.django_db
    def test_maximum_power_when_connector_max_electric_power_none_and_connector_max_electric_power_10kw(
        self, connector_max_electric_power_10kw, connector_max_electric_power_none
    ):
        max_power = self._ocpi_2_oicp_converter.get_maximum_product_charging_power()
        assert max_power == 10

    @pytest.mark.parametrize(
        "solid_tariff_id, ref_unit, operator_id, msp_id, expected",
        [
            (
                "SMP1",
                HubjectPriceComponent.MINUTE,
                "BE*SMP",
                "DE*ICE",
                "BE*SMP*SMP1*MINUTE*DE*ICE",
            ),
            (
                "SMP2",
                HubjectPriceComponent.KWH,
                "NL*CPO",
                "FR*MSP",
                "NL*CPO*SMP2*KILOWATT_HOUR*FR*MSP",
            ),
            (
                "SMP3",
                HubjectPriceComponent.HOUR,
                "US*CPO",
                "GB*MSP",
                "US*CPO*SMP3*HOUR*GB*MSP",
            ),
            ("SMP3", HubjectPriceComponent.HOUR, "US*CPO", "", "US*CPO*SMP3*HOUR*"),
        ],
    )
    def test_get_pricing_product_id(
        self, solid_tariff_id, ref_unit, operator_id, msp_id, expected
    ):
        result = self._ocpi_2_oicp_converter.get_pricing_product_id(
            solid_tariff_id, ref_unit, operator_id, msp_id
        )
        assert result == expected, f"Expected {expected}, but got {result}"

    def test_get_pricing_product_id_raises_value_error_when_none_values_provided(self):
        with pytest.raises(
            ValueError,
            match="Missing required fields {operator_id, price_reference, solid_tariff_external_id} for generating pricing product ID.",
        ):
            self._ocpi_2_oicp_converter.get_pricing_product_id(None, None, None, "")

    @pytest.mark.django_db
    def test_convert_to_pricing_product_data_records_success(
        self,
        smp1_solid_tariff_with_all_records,
        pricing_product_data_record_successful_result,
    ):
        pricing_product_data_records = (
            self._ocpi_2_oicp_converter.convert_to_pricing_product_data_records(
                smp1_solid_tariff_with_all_records, "FI*CPO"
            )
        )
        assert len(pricing_product_data_records) == 2
        assert (
            pricing_product_data_records
            == pricing_product_data_record_successful_result
        )

    def expected_helsinki_eroaming_push_evse_data(self, evse_id: str):
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
                            "TimeZone": "UTC+02:00",
                        },
                        "AuthenticationModes": [AuthenticationMode.NFC_RFID_Classic],
                        "CalibrationLawDataAvailability": CalibrationLawDataAvailability.Local,
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
                        "ChargingStationId": None,
                        "ChargingStationImage": None,
                        "ChargingStationLocationReference": None,
                        "ChargingStationNames": [
                            {"lang": "en", "value": "Helsinki Supercharger"}
                        ],
                        "ClearinghouseID": None,
                        "DynamicInfoAvailable": DynamicInfoAvailable.false,
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
                        "IsHubjectCompatible": False,
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

    def expected_berlin_eroaming_push_evse_data(self, evse_id: str):
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
                            "TimeZone": "UTC+01:00",
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
                        "ChargingStationId": None,
                        "ChargingStationImage": None,
                        "ChargingStationLocationReference": None,
                        "ChargingStationNames": [
                            {"lang": "en", "value": "Berlin Location"}
                        ],
                        "ClearinghouseID": None,
                        "DynamicInfoAvailable": DynamicInfoAvailable.false,
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
                        "IsHubjectCompatible": False,
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
