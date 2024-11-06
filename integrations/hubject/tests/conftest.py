from datetime import datetime

import pytest
import pytz

from integrations.hubject.schemas import (
    AuthenticationMode,
    Plug,
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
)
from ocpi22.tests.factories import (
    LocationFactory,
    ConnectorFactory,
    EvseFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    EvseDataRecordFactory,
    AddressFactory,
    OperatorEvseDataFactory,
)


@pytest.fixture
def helsinki_location():
    helsinki_supercharger_ocpi_master = CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
        business_details=BusinessDetailsFactory(
            name="Smappee Pvt Ltd",
            website="https://www.helsinki-supercharger.com",
            logo="https://www.helsinki-supercharger.com/static/test_logo.png",
        ),
    )
    helsinki_supercharger_operator_business_details = BusinessDetailsFactory(
        name="Helsinki Supercharger Operator",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
    )
    helsinki_supercharger_sub_operator_business_details = BusinessDetailsFactory(
        name="Helsinki Supercharger Sub Operator",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
    )
    helsinki_supercharger_owner_business_details = BusinessDetailsFactory(
        name="Smappee Pvt Ltd.",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
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

    return helsinki


@pytest.fixture
def berlin_emsdetten_location():
    berlin_supercharger_ocpi_master = CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
    )

    berlin_location = LocationFactory(
        name="Berlin Location",
        address="Ansgarstr. 4",
        city="Wallenhorst",
        postal_code="49134",
        state="",
        country="DEU",
        latitude=9.360922,
        longitude=47.662249,
        time_zone="Europe/Berlin",
        ocpi_master=berlin_supercharger_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )

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
        ocpi_master=berlin_supercharger_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )

    berlin_evse_data = EvseFactory.build(
        evse_id="FI*ABC*1234*C0*CT",
        status="",
        location=berlin_location,
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )

    emsdetten_evse_data = EvseFactory.build(
        evse_id="FI*ABC*1234*C2*CT",
        status="",
        location=emsdetten_location,
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )

    ConnectorFactory.build(
        uid="CONNECTOR_1",
        evse=berlin_evse_data,
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        max_electric_power=1400,
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )

    ConnectorFactory.build(
        uid="CONNECTOR_2",
        evse=emsdetten_evse_data,
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        max_electric_power=1400,
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )

    return [berlin_location, emsdetten_location]


@pytest.fixture
def berlin_emsdetten_op_evse_data(berlin_emsdetten_evse_data_records):
    berlin_mock_op_evse_data = OperatorEvseDataFactory.build(
        OperatorID="DE*SMP",
        OperatorName="Smappee Operator",
        EvseDataRecord=[berlin_emsdetten_evse_data_records[0]],
    )

    emsdetten_mock_op_evse_data = OperatorEvseDataFactory.build(
        OperatorID="DE*SMP",
        OperatorName="Smappee Operator",
        EvseDataRecord=[berlin_emsdetten_evse_data_records[1]],
    )

    return [berlin_mock_op_evse_data, emsdetten_mock_op_evse_data]


@pytest.fixture
def berlin_emsdetten_evse_data_records():
    berlin_evse_data_record = EvseDataRecordFactory.build(
        lastUpdate=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        EvseID="FI*ABC*E1234*C0*CT",
        Address=AddressFactory(
            Country="DEU",
            City="Wallenhorst",
            Street="Evolis",
            PostalCode="49134",
            HouseNum="4",
            ParkingFacility=True,
            TimeZone="UTC+01:00",
        ),
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
        PaymentOptions=["Direct"],
        ValueAddedServices=["Reservation"],
        AccessibilityLocation="OnStreet",
        HotlinePhoneNumber="+3256380211",
        IsHubjectCompatible=False,
        DynamicInfoAvailable="false",
    )

    emsdetten_evse_data_record = EvseDataRecordFactory.build(
        lastUpdate=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        EvseID="FI*ABC*E1234*C0*CT",
        Address=AddressFactory(
            Country="DEU",
            City="Harelbeke",
            Street="Südring",
            PostalCode="38170",
            HouseNum="25",
            Floor="1",
            Region="Flanders",
            ParkingFacility=True,
            ParkingSpot="Parking Spot1",
            TimeZone="UTC+01:00",
        ),
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
        PaymentOptions=["Direct"],
        ValueAddedServices=["Reservation"],
        AccessibilityLocation="OnStreet",
        HotlinePhoneNumber="+3256380211",
        IsHubjectCompatible=False,
        DynamicInfoAvailable="false",
    )

    return [berlin_evse_data_record, emsdetten_evse_data_record]


@pytest.fixture
def evse_full_load_payload(
    berlin_emsdetten_evse_data_records, berlin_emsdetten_op_evse_data
):
    return ERoamingPushEvseData(
        ActionType=ActionType.fullLoad,
        OperatorEvseData=OperatorEvseData(
            OperatorID=berlin_emsdetten_op_evse_data[0].OperatorID,
            OperatorName=berlin_emsdetten_op_evse_data[0].OperatorName,
            EvseDataRecord=[berlin_emsdetten_evse_data_records[0]],
        ),
    )
