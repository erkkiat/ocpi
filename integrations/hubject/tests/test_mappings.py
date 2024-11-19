import doctest
from datetime import datetime, timezone

import pytest
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
)
from integrations.hubject_to_ocpi_converter import HubjectToOCPIConverter
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Connector


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("integrations.solid_to_hubject_converter"))
    tests.addTests(doctest.DocTestSuite("integrations.hubject_to_ocpi_converter"))
    return tests


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
    def test_map_location_to_eroaming_push_evse_data(self, helsinki_location):
        evse_id = helsinki_location.evses.first().evse_id
        expected_data = self.expected_helsinki_eroaming_push_evse_data(evse_id)

        helsinki_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=self._ocpi_2_oicp_converter.convert_to_operator_evse_data(
                helsinki_location
            ),
        )
        assert helsinki_location.evses.count() == 1
        assert (
            helsinki_hubject_evse_data.model_dump() == expected_data
        ), "The mapped OCPI Location data does not match the expected OICP data."

    @pytest.mark.django_db
    def test_convert_to_eroaming_with_only_required_data(self, berlin_location):
        evse_id = berlin_location.evses.first().evse_id
        berlin_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=TestMappings._ocpi_2_oicp_converter.convert_to_operator_evse_data(
                berlin_location
            ),
        )

        assert berlin_location.evses.count() == 1
        assert (
            berlin_hubject_evse_data.model_dump()
            == self.expected_berlin_eroaming_push_evse_data(evse_id)
        ), "The mapped OCPI Location data does not match the expected OICP data."

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
                            2024, 9, 22, 17, 32, 8, 599540, tzinfo=timezone.utc
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
                            2024, 9, 22, 17, 32, 8, 599540, tzinfo=timezone.utc
                        ),
                    }
                ],
            },
        }
