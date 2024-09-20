from django.test import TestCase
from rest_framework.exceptions import ValidationError

from hubject.factories import LocationFactory
from hubject.mappings import (
    map_connector_std_choices_to_plug,
    get_distinct_plugs_from_connector_std_choices,
    map_power_type_choices_221_to_power_type,
    get_all_charging_facilities_from_connectors,
    map_location_to_eroaming_push_evse_data,
    get_all_authentication_modes_from_capabilities,
    split_address_into_street_and_house_number,
    get_all_value_added_services_from_capabilities,
    map_parking_types_to_accessibility_locations,
)
from hubject.models import Plug, PowerType, ChargingFacility, AuthenticationMode
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Connector
from ocpiconnector import settings
import doctest


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("hubject.mappings"))
    return tests


class TestMappings(TestCase):
    def test_map_connector_std_choices_to_plug_unknown(self):
        with self.assertRaises(ValidationError):
            map_connector_std_choices_to_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        expected_plugs = [Plug.CHAdeMO, Plug.Type_2_Outlet]
        mapped_plugs = get_distinct_plugs_from_connector_std_choices(connectors)
        self.assertTrue(expected_plugs[0] in mapped_plugs)
        self.assertTrue(expected_plugs[1] in mapped_plugs)

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
        self.assertEqual(
            get_all_charging_facilities_from_connectors(connectors), expected_facilities
        )

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        self.assertEqual(
            get_all_authentication_modes_from_capabilities(capabilities),
            authentication_modes,
        )

    def test_map_ocpi_location_to_hubject_eroaming_push_evse_data(self):
        fake_location = LocationFactory()
        fake_location_evse = fake_location.evses.all()[0]
        fake_eroaming_push_evse_data = map_location_to_eroaming_push_evse_data(
            fake_location
        )
        fake_operator_evse_data = fake_eroaming_push_evse_data.OperatorEvseData
        fake_evse_data = fake_operator_evse_data.EvseDataRecord[0]

        self.assertEqual(fake_operator_evse_data.OperatorID.root, fake_location.party())
        self.assertEqual(fake_operator_evse_data.OperatorName, fake_location.owner.name)
        self.assertEqual(fake_evse_data.EvseID.root, fake_location_evse.evse_id)
        self.assertEqual(fake_evse_data.Address.Country, fake_location.country)
        self.assertEqual(fake_evse_data.Address.City, fake_location.city)
        self.assertEqual(fake_evse_data.Address.PostalCode, fake_location.postal_code)
        self.assertEqual(
            fake_evse_data.Address.Street,
            split_address_into_street_and_house_number(fake_location.address).get(
                "street", "-"
            ),
        )
        self.assertEqual(
            fake_evse_data.Address.HouseNum,
            split_address_into_street_and_house_number(fake_location.address).get(
                "house", "-"
            ),
        )
        self.assertEqual(
            fake_evse_data.Address.ParkingFacility,
            fake_location.parking_type is not None,
        )
        self.assertEqual(fake_evse_data.Address.TimeZone, fake_location.time_zone)
        self.assertEqual(
            fake_evse_data.GeoCoordinates.DecimalDegree.Latitude,
            str(fake_location.latitude),
        )
        self.assertEqual(
            fake_evse_data.GeoCoordinates.DecimalDegree.Longitude,
            str(fake_location.longitude),
        )
        self.assertEqual(
            fake_evse_data.Plugs,
            get_distinct_plugs_from_connector_std_choices(
                fake_location_evse.connectors.all()
            ),
        )
        self.assertEqual(
            fake_evse_data.ChargingFacilities,
            get_all_charging_facilities_from_connectors(
                fake_location_evse.connectors.all()
            ),
        )
        self.assertEqual(
            fake_evse_data.AuthenticationModes,
            get_all_authentication_modes_from_capabilities(
                fake_location_evse.capabilities
            ),
        )
        self.assertEqual(
            fake_evse_data.ValueAddedServices,
            get_all_value_added_services_from_capabilities(
                fake_location_evse.capabilities
            ),
        )
        self.assertEqual(
            fake_evse_data.AccessibilityLocation,
            map_parking_types_to_accessibility_locations(fake_location.parking_type),
        )
        self.assertEqual(fake_evse_data.HotlinePhoneNumber, settings.HOTLINE)
        self.assertEqual(
            fake_evse_data.GeoChargingPointEntrance.DecimalDegree.Latitude,
            str(fake_location.latitude),
        )
        self.assertEqual(
            fake_evse_data.GeoChargingPointEntrance.DecimalDegree.Longitude,
            str(fake_location.longitude),
        )
        self.assertEqual(
            fake_evse_data.IsOpen24Hours, fake_location.charging_when_closed
        )

    def test_map_location_to_eroaming_push_evse_data_custom_attributes(self):
        fake_location = LocationFactory(city="New City", country="FIN")
        fake_location_evse = fake_location.evses.all()[1]
        fake_eroaming_push_evse_data = map_location_to_eroaming_push_evse_data(
            fake_location
        )
        fake_operator_evse_data = fake_eroaming_push_evse_data.OperatorEvseData
        fake_evse_data = fake_operator_evse_data.EvseDataRecord[1]

        self.assertEqual(fake_operator_evse_data.OperatorID.root, fake_location.party())
        self.assertEqual(fake_operator_evse_data.OperatorName, fake_location.owner.name)
        self.assertEqual(fake_evse_data.EvseID.root, fake_location_evse.evse_id)
        self.assertEqual(fake_evse_data.Address.Country, "FIN")
        self.assertEqual(fake_evse_data.Address.City, "New City")
        self.assertEqual(fake_evse_data.Address.PostalCode, fake_location.postal_code)
        self.assertEqual(
            fake_evse_data.Address.Street,
            split_address_into_street_and_house_number(fake_location.address).get(
                "street", "-"
            ),
        )
        self.assertEqual(
            fake_evse_data.Address.HouseNum,
            split_address_into_street_and_house_number(fake_location.address).get(
                "house", "-"
            ),
        )
        self.assertEqual(
            fake_evse_data.Address.ParkingFacility,
            fake_location.parking_type is not None,
        )
        self.assertEqual(fake_evse_data.Address.TimeZone, fake_location.time_zone)
        self.assertEqual(
            fake_evse_data.GeoCoordinates.DecimalDegree.Latitude,
            str(fake_location.latitude),
        )
        self.assertEqual(
            fake_evse_data.GeoCoordinates.DecimalDegree.Longitude,
            str(fake_location.longitude),
        )
        self.assertEqual(
            fake_evse_data.Plugs,
            get_distinct_plugs_from_connector_std_choices(
                fake_location_evse.connectors.all()
            ),
        )
        self.assertEqual(
            fake_evse_data.ChargingFacilities,
            get_all_charging_facilities_from_connectors(
                fake_location_evse.connectors.all()
            ),
        )
        self.assertEqual(
            fake_evse_data.AuthenticationModes,
            get_all_authentication_modes_from_capabilities(
                fake_location_evse.capabilities
            ),
        )
        self.assertEqual(
            fake_evse_data.ValueAddedServices,
            get_all_value_added_services_from_capabilities(
                fake_location_evse.capabilities
            ),
        )
        self.assertEqual(
            fake_evse_data.AccessibilityLocation,
            map_parking_types_to_accessibility_locations(fake_location.parking_type),
        )
        self.assertEqual(fake_evse_data.HotlinePhoneNumber, settings.HOTLINE)
        self.assertEqual(
            fake_evse_data.GeoChargingPointEntrance.DecimalDegree.Latitude,
            str(fake_location.latitude),
        )
        self.assertEqual(
            fake_evse_data.GeoChargingPointEntrance.DecimalDegree.Longitude,
            str(fake_location.longitude),
        )
        self.assertEqual(
            fake_evse_data.IsOpen24Hours, fake_location.charging_when_closed
        )
