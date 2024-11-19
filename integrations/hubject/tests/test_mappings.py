import doctest

import pytest
from django.core.exceptions import ValidationError

from integrations.hubject.schemas import (
    Plug,
    PowerType,
    ChargingFacility,
    AuthenticationMode,
    ActionType,
    ERoamingPushEvseData,
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
    __ocpi_2_oicp_converter = SolidToHubjectConverter()
    __oicp_to_ocpi_converter = HubjectToOCPIConverter()

    def test_map_connector_std_choices_to_plug_unknown(self):
        with pytest.raises(ValidationError):
            TestMappings.__ocpi_2_oicp_converter.get_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        mapped_plugs = TestMappings.__ocpi_2_oicp_converter.get_distinct_plugs(
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
            TestMappings.__ocpi_2_oicp_converter.get_power_type("UNKNOWN_POWER_TYPE")

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
            TestMappings.__ocpi_2_oicp_converter.get_charging_facilities(connectors)
            == expected_facilities
        )

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        assert (
            TestMappings.__ocpi_2_oicp_converter.get_authentication_modes_list(
                capabilities
            )
            == authentication_modes
        )

    def test_accessibility_locations_when_parking_type_none(self):
        assert (
            TestMappings.__ocpi_2_oicp_converter.get_accessibility_locations(None)
            is None
        )

    @pytest.mark.django_db
    def test_map_location_to_eroaming_push_evse_data(
        self,
        helsinki_location,
        helsinki_evse,
        helsinki_connector,
        expected_helsinki_eroaming_push_evse_data,
    ):
        helsinki_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=TestMappings.__ocpi_2_oicp_converter.convert_to_operator_evse_data(
                helsinki_location
            ),
        )
        assert (
            helsinki_hubject_evse_data.model_dump()
            == expected_helsinki_eroaming_push_evse_data
        ), "The mapped OCPI Location data does not match the expected OICP data."

    @pytest.mark.django_db
    def test_convert_to_eroaming_with_only_required_data(
        self, berlin_location, expected_berlin_eroaming_push_evse_data
    ):
        berlin_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=TestMappings.__ocpi_2_oicp_converter.convert_to_operator_evse_data(
                berlin_location
            ),
        )

        assert (
            berlin_hubject_evse_data.model_dump()
            == expected_berlin_eroaming_push_evse_data
        ), "The mapped OCPI Location data does not match the expected OICP data."
