from django.test import TestCase
from rest_framework.exceptions import ValidationError

from ocpi22.tests.factories import LocationFactory
from integrations.hubject.mappings import (
    map_connector_to_plug,
    get_distinct_plugs,
    map_power_type_choices_221_to_power_type,
    get_all_charging_facilities,
    map_location_to_eroaming_push_evse_data,
    get_all_authentication_modes,
    get_all_value_added_services,
    map_ocpi_parking_types_to_accessibility_locations,
    get_street,
    get_house_number,
)
from integrations.hubject.schemas import (
    Plug,
    PowerType,
    ChargingFacility,
    AuthenticationMode,
)
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Connector
from ocpiconnector import testutil
import ocpiconnector.settings.base as settings
import doctest


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("hubject.mappings"))
    return tests


class TestMappings(TestCase):
    def test_map_connector_std_choices_to_plug_unknown(self):
        with self.assertRaises(ValidationError):
            map_connector_to_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        expected_plugs = [Plug.CHAdeMO, Plug.Type_2_Outlet]
        mapped_plugs = get_distinct_plugs(connectors)

        result = testutil.compare_lists_recursively(mapped_plugs, expected_plugs)
        self.assertTrue(result, "The mapped plugs do not match the expected plugs.")

    def test_map_power_type_choices_221_to_power_type_unknown(self):
        with self.assertRaises(ValidationError):
            map_power_type_choices_221_to_power_type("UNKNOWN_POWER_TYPE")

    def test_get_all_charging_facilities_from_connectors(self):
        connectors = [
            Connector(
                power_type=["AC_1_PHASE"],
                max_voltage=230,
                max_amperage=16,
                max_electric_power=37,
            ),
            Connector(
                power_type=["DC"],
                max_voltage=401,
                max_amperage=45,
                max_electric_power=50,
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
        self.assertEqual(get_all_charging_facilities(connectors), expected_facilities)

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        self.assertEqual(
            get_all_authentication_modes(capabilities),
            authentication_modes,
        )

    def test_map_ocpi_location_to_hubject_eroaming_push_evse_data(self):
        berlin = LocationFactory()
        berlin_evse = berlin.evses.all()[0]
        berlin_hubject_evse_data = map_location_to_eroaming_push_evse_data(berlin)
        berlin_operator_evse_data = berlin_hubject_evse_data.OperatorEvseData
        berlin_evse_data_first_record = berlin_operator_evse_data.EvseDataRecord[0]

        self.assertEqual(berlin_operator_evse_data.OperatorID.root, berlin.party())
        self.assertEqual(berlin_operator_evse_data.OperatorName, berlin.owner.name)
        self.assertEqual(berlin_evse_data_first_record.EvseID.root, berlin_evse.evse_id)
        self.assertEqual(berlin_evse_data_first_record.Address.Country, berlin.country)
        self.assertEqual(berlin_evse_data_first_record.Address.City, berlin.city)
        self.assertEqual(
            berlin_evse_data_first_record.Address.PostalCode, berlin.postal_code
        )
        self.assertEqual(
            berlin_evse_data_first_record.Address.Street,
            get_street(berlin.address),
        )
        self.assertEqual(
            berlin_evse_data_first_record.Address.HouseNum,
            get_house_number(berlin.address),
        )
        self.assertEqual(
            berlin_evse_data_first_record.Address.ParkingFacility,
            berlin.parking_type is not None,
        )
        self.assertEqual(
            berlin_evse_data_first_record.Address.TimeZone, berlin.time_zone
        )
        self.assertEqual(
            berlin_evse_data_first_record.GeoCoordinates.DecimalDegree.Latitude,
            str(berlin.latitude),
        )
        self.assertEqual(
            berlin_evse_data_first_record.GeoCoordinates.DecimalDegree.Longitude,
            str(berlin.longitude),
        )
        self.assertEqual(
            berlin_evse_data_first_record.Plugs,
            get_distinct_plugs(berlin_evse.connectors.all()),
        )
        self.assertEqual(
            berlin_evse_data_first_record.ChargingFacilities,
            get_all_charging_facilities(berlin_evse.connectors.all()),
        )
        self.assertEqual(
            berlin_evse_data_first_record.AuthenticationModes,
            get_all_authentication_modes(berlin_evse.capabilities),
        )
        self.assertEqual(
            berlin_evse_data_first_record.ValueAddedServices,
            get_all_value_added_services(berlin_evse.capabilities),
        )
        self.assertEqual(
            berlin_evse_data_first_record.AccessibilityLocation,
            map_ocpi_parking_types_to_accessibility_locations(berlin.parking_type),
        )
        self.assertEqual(
            berlin_evse_data_first_record.HotlinePhoneNumber, settings.HOTLINE
        )
        self.assertEqual(
            berlin_evse_data_first_record.GeoChargingPointEntrance.DecimalDegree.Latitude,
            str(berlin.latitude),
        )
        self.assertEqual(
            berlin_evse_data_first_record.GeoChargingPointEntrance.DecimalDegree.Longitude,
            str(berlin.longitude),
        )
        self.assertEqual(
            berlin_evse_data_first_record.IsOpen24Hours, berlin.charging_when_closed
        )

    def test_map_location_to_eroaming_push_evse_data_custom_attributes(self):
        helsinki = LocationFactory(city="Helsinki", country="FIN")
        helsinki_evse = helsinki.evses.all()[1]
        helsinki_hubject_evse_data = map_location_to_eroaming_push_evse_data(helsinki)
        helsinki_operator_evse_data = helsinki_hubject_evse_data.OperatorEvseData
        helsinki_evse_data_first_record = helsinki_operator_evse_data.EvseDataRecord[1]

        self.assertEqual(helsinki_operator_evse_data.OperatorID.root, helsinki.party())
        self.assertEqual(helsinki_operator_evse_data.OperatorName, helsinki.owner.name)
        self.assertEqual(
            helsinki_evse_data_first_record.EvseID.root, helsinki_evse.evse_id
        )
        self.assertEqual(helsinki_evse_data_first_record.Address.Country, "FIN")
        self.assertEqual(helsinki_evse_data_first_record.Address.City, "Helsinki")
        self.assertEqual(
            helsinki_evse_data_first_record.Address.PostalCode, helsinki.postal_code
        )
        self.assertEqual(
            helsinki_evse_data_first_record.Address.Street,
            get_street(helsinki.address),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.Address.HouseNum,
            get_house_number(helsinki.address),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.Address.ParkingFacility,
            helsinki.parking_type is not None,
        )
        self.assertEqual(
            helsinki_evse_data_first_record.Address.TimeZone, helsinki.time_zone
        )
        self.assertEqual(
            helsinki_evse_data_first_record.GeoCoordinates.DecimalDegree.Latitude,
            str(helsinki.latitude),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.GeoCoordinates.DecimalDegree.Longitude,
            str(helsinki.longitude),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.Plugs,
            get_distinct_plugs(helsinki_evse.connectors.all()),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.ChargingFacilities,
            get_all_charging_facilities(helsinki_evse.connectors.all()),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.AuthenticationModes,
            get_all_authentication_modes(helsinki_evse.capabilities),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.ValueAddedServices,
            get_all_value_added_services(helsinki_evse.capabilities),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.AccessibilityLocation,
            map_ocpi_parking_types_to_accessibility_locations(helsinki.parking_type),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.HotlinePhoneNumber, settings.HOTLINE
        )
        self.assertEqual(
            helsinki_evse_data_first_record.GeoChargingPointEntrance.DecimalDegree.Latitude,
            str(helsinki.latitude),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.GeoChargingPointEntrance.DecimalDegree.Longitude,
            str(helsinki.longitude),
        )
        self.assertEqual(
            helsinki_evse_data_first_record.IsOpen24Hours, helsinki.charging_when_closed
        )
