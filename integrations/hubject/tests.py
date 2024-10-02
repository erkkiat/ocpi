from django.test import TestCase
from django.utils.datetime_safe import datetime
from django.core.exceptions import ValidationError

from integrations.ocpi_to_hubject_converter import OCPIToHubjectConverter

from integrations.hubject.test_data import ERoamingPushTestData
from ocpi22.tests.factories import (
    LocationFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    EvseFactory,
    ConnectorFactory,
)

from integrations.hubject.schemas import (
    Plug,
    PowerType,
    ChargingFacility,
    AuthenticationMode,
    ActionType,
    ERoamingPushEvseData,
)
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Connector
from ocpiconnector import testutil

import doctest
import pytz


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("integrations.ocpi_to_hubject_converter"))
    return tests


class TestMappings(TestCase):
    def setUp(self):
        self.ocpi_2_oicp_converter = OCPIToHubjectConverter(
            oicp_version="2.2.1",
            ocpi_version="2.3",
        )

    def test_map_connector_std_choices_to_plug_unknown(self):
        with self.assertRaises(ValidationError):
            self.ocpi_2_oicp_converter.get_plug("UNKNOWN_PLUG")

    def test_get_distinct_plugs_from_connector_std_choices(self):
        connectors = [Connector(standard="CHADEMO"), Connector(standard="IEC_62196_T2")]
        mapped_plugs = self.ocpi_2_oicp_converter.get_distinct_plugs(connectors)

        self.assertTrue(
            Plug.CHAdeMO in mapped_plugs, "The CHAdeMO plug is not in the mapped plugs."
        )
        self.assertTrue(
            Plug.Type_2_Outlet in mapped_plugs,
            "The Type 2 Outlet plug is not in the mapped plugs.",
        )

    def test_map_power_type_choices_221_to_power_type_unknown(self):
        with self.assertRaises(ValidationError):
            self.ocpi_2_oicp_converter.get_power_type("UNKNOWN_POWER_TYPE")

    def test_get_all_charging_facilities_from_connectors(self):
        connectors = [
            Connector(
                power_type="AC_1_PHASE",
                max_voltage=230,
                max_amperage=16,
                max_electric_power=37,
            ),
            Connector(
                power_type="DC",
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
            self.ocpi_2_oicp_converter.get_charging_facilities(connectors),
            expected_facilities,
        )

    def test_get_all_authentication_modes_from_capabilities(self):
        capabilities = [OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.RESERVABLE]

        authentication_modes = [AuthenticationMode.NFC_RFID_Classic]
        self.assertEqual(
            self.ocpi_2_oicp_converter.get_authentication_modes_list(capabilities),
            authentication_modes,
        )

    def test_map_location_to_eroaming_push_evse_data(self):
        helsinki_supercharger_ocpi_master = CredentialsRoleFactory(
            role="CPO",
            country_code="DE",
            party_id="SMP",
        )
        helsinki_supercharger_operator_business_details = BusinessDetailsFactory(
            name="Helsinki Supercharger Operator",
            website="https://www.helsinki-supercharger.com",
            logo="test_logo.png",
        )
        helsinki_supercharger_sub_operator_business_details = BusinessDetailsFactory(
            name="Helsinki Supercharger Sub Operator",
            website="https://www.helsinki-supercharger.com",
            logo="test_logo.png",
        )
        helsinki_supercharger_owner_business_details = BusinessDetailsFactory(
            name="Smappee Pvt Ltd.",
            website="https://www.helsinki-supercharger.com",
            logo="test_logo.png",
        )

        helsinki = LocationFactory(
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
            ocpi_master=helsinki_supercharger_ocpi_master,
            operator=helsinki_supercharger_operator_business_details,
            suboperator=helsinki_supercharger_sub_operator_business_details,
            owner=helsinki_supercharger_owner_business_details,
            charging_when_closed=True,
        )

        helsinki_evse_data = EvseFactory(
            evse_id="FI*ABC*E1234*5668",
            status="RESERVED",
            location=helsinki,
            last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
            updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
            created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
            capabilities=["RFID_READER", "RESERVABLE"],
        )

        ConnectorFactory(
            uid="CONNECTOR_1",
            evse=helsinki_evse_data,
            standard="IEC_62196_T2",
            format="SOCKET",
            power_type="DC",
            max_voltage=230,
            max_amperage=16,
            max_electric_power=37,
            terms_and_conditions="https://www.helsinki-supercharger.com/terms-and-conditions",
            last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
            updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
            created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        )

        helsinki_hubject_evse_data = ERoamingPushEvseData(
            ActionType=ActionType.insert,
            OperatorEvseData=self.ocpi_2_oicp_converter.convert_to_operator_evse_data(
                helsinki
            ),
        )

        # Remove automatically generated EVSE data
        helsinki_hubject_evse_data.OperatorEvseData.EvseDataRecord = [
            helsinki_hubject_evse_data.OperatorEvseData.EvseDataRecord[-1]
        ]

        result = testutil.compare_dicts_recursively(
            helsinki_hubject_evse_data.model_dump(),
            ERoamingPushTestData.helsinki_eroaming_push_data,
        )
        self.assertTrue(
            result,
            "The mapped OCPI Location data does not match the expected OICP data.",
        )
