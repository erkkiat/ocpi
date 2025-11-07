from datetime import datetime
from decimal import Decimal

import factory
import pytest
import pytz

from integrations.hubject.schemas import (
    AuthenticationMode,
    Plug,
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    InfoTextType,
    DecimalDegree,
    ValueAddedService,
    PowerType,
    PaymentOption,
    PricingProductDataRecord,
    AdditionalReference,
    AdditionalReferenceChoice,
    ReferenceUnit,
    HubjectPriceComponent,
    PricingProductData,
    OperatorID,
    ProviderIDAsterisk,
    CurrencyID,
    ProductID,
    ChargingFacility,
    Accessibility,
    DynamicInfoAvailable,
    GeoCoordinates,
    Address,
    EvseID,
    EvseDataRecord,
    CalibrationLawDataAvailability,
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
    GeoCoordinatesFactory,
    ChargingFacilityFactory,
    TariffFactory,
    OCPIImageFactory,
    SolidTariffFactory,
    ERoamingPushPricingProductDataFactory,
    CdrTokenFactory,
    OCPISessionFactory,
    CdrFactory,
    CdrLocationFactory,
)


@pytest.fixture
def smappee_business_details():
    return BusinessDetailsFactory(
        name="Smappee Pvt Ltd",
        website="https://www.helsinki-supercharger.com",
        logo=factory.SubFactory(OCPIImageFactory),
    )


@pytest.fixture
def helsinki_ocpi_master(smappee_business_details):
    return CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
        business_details=smappee_business_details,
    )


@pytest.fixture
def helsinki_operator_details():
    return BusinessDetailsFactory(
        name="Helsinki Supercharger Operator",
        website="https://www.helsinki-supercharger.com",
        logo=factory.SubFactory(OCPIImageFactory),
    )


@pytest.fixture
def helsinki_sub_operator_details(helsinki_ocpi_master):
    return BusinessDetailsFactory(
        name="Helsinki Supercharger Sub Operator",
        website="https://www.helsinki-supercharger.com",
        logo=factory.SubFactory(OCPIImageFactory),
    )


@pytest.fixture
def helsinki_owner_details():
    return BusinessDetailsFactory(
        name="Smappee Pvt Ltd.",
        website="https://www.helsinki-supercharger.com",
        logo=factory.SubFactory(OCPIImageFactory),
    )


@pytest.fixture
def helsinki_evse(helsinki_connector):
    helsinki_evse = EvseFactory(
        status="RESERVED",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=["RFID_READER", "RESERVABLE"],
    )
    helsinki_evse.connectors.set([helsinki_connector])
    return helsinki_evse


@pytest.fixture
def helsinki_connector():
    return ConnectorFactory(
        uid="CONNECTOR_1",
        standard="IEC_62196_T2",
        format="SOCKET",
        power_type="DC",
        max_voltage=230,
        max_amperage=16,
        max_electric_power=37000,
        terms_and_conditions="https://www.helsinki-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def helsinki_location(
    helsinki_ocpi_master,
    helsinki_operator_details,
    helsinki_sub_operator_details,
    helsinki_owner_details,
    helsinki_evse,
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

    helsinki_location.evses.add(helsinki_evse)
    return helsinki_location


@pytest.fixture
def berlin_ocpi_master(smappee_business_details):
    return CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
        business_details=smappee_business_details,
    )


@pytest.fixture
def emsdetten_ocpi_master(smappee_business_details):
    return CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="EMP",
        business_details=smappee_business_details,
    )


@pytest.fixture
def berlin_evse_data(berlin_connector):
    berlin_evse_data = EvseFactory(
        uid="berlinevseuid",
        evse_id="FI*ABC*1234*C0*CT",
        status="",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )
    berlin_evse_data.connectors.set([berlin_connector])
    return berlin_evse_data


@pytest.fixture
def berlin_connector(berlin_tariff):
    return ConnectorFactory(
        uid="CONNECTOR_1",
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        tariff_ids=[berlin_tariff],
        max_electric_power=12000,
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def berlin_location(berlin_ocpi_master, berlin_evse_data):
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
    berlin_location.evses.set([berlin_evse_data])
    return berlin_location


@pytest.fixture
def emsdetten_location(emsdetten_ocpi_master, emsdetten_evse):
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
    emsdetten_location.evses.set([emsdetten_evse])
    return emsdetten_location


@pytest.fixture
def emsdetten_evse(emsdetten_connector):
    emsdetten_evse = EvseFactory(
        uid="Eemsdettenevseuid",
        evse_id="FI*ABC*1234*C2*CT",
        status="",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )
    emsdetten_evse.connectors.set([emsdetten_connector])
    return emsdetten_evse


@pytest.fixture
def emsdetten_connector(emsdetten_tariff):
    return ConnectorFactory(
        uid="CONNECTOR_2",
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        max_electric_power=1400,
        tariff_ids=[emsdetten_tariff],
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def emsdetten_tariff():
    return TariffFactory()


@pytest.fixture
def berlin_tariff():
    return TariffFactory()


@pytest.fixture
def emsdetten_op_evse_data(emsdetten_evse_data_record):
    return OperatorEvseDataFactory.build(
        OperatorID="DE*EMP",
        OperatorName="Smappee Pvt Ltd",
        EvseDataRecord=[emsdetten_evse_data_record],
    )


@pytest.fixture
def berlin_op_evse_data(berlin_evse_data_record):
    return OperatorEvseDataFactory.build(
        OperatorID="DE*SMP",
        OperatorName="Smappee Pvt Ltd",
        EvseDataRecord=[berlin_evse_data_record],
    )


@pytest.fixture
def berlin_evse_data_record():
    return EvseDataRecordFactory.build(
        deltaType=None,
        lastUpdate=datetime(2024, 9, 22, 17, 32, 8, 599540, tzinfo=pytz.UTC),
        EvseID="DE*SMP*Eberlinevseuid",
        Address=AddressFactory(
            Country="DEU",
            City="Wallenhorst",
            Street="Ansgarstr.",
            PostalCode="",
            HouseNum="4",
            TimeZone="UTC+01:00",
            Floor=None,
            Region=None,
            ParkingSpot=None,
            ParkingFacility=False,
        ),
        GeoChargingPointEntrance=GeoCoordinatesFactory(
            Google=None,
            DegreeMinuteSeconds=None,
            DecimalDegree=DecimalDegree(Longitude="0.000000", Latitude="0.000000"),
        ),
        GeoCoordinates=GeoCoordinatesFactory(
            Google=None,
            DegreeMinuteSeconds=None,
            DecimalDegree=DecimalDegree(Longitude="0.000000", Latitude="0.000000"),
        ),
        ChargingStationNames=[InfoTextType(lang="en", value="Berlin Location")],
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
        PaymentOptions=[PaymentOption.Contract],
        ValueAddedServices=[ValueAddedService.None_],
        ChargingStationId=None,
        HardwareManufacturer=None,
        ChargingStationImage=None,
        ChargingFacilities=[
            ChargingFacilityFactory(
                PowerType=PowerType.AC_3_PHASE,
                Voltage=0,
                Amperage=16,
                Power=12,
                ChargingModes=None,
            )
        ],
        MaxCapacity=None,
        ClearinghouseID=None,
        EnergySource=None,
        SubOperatorName=None,
        AccessibilityLocation=None,
        HotlinePhoneNumber="+3256380211",
        AdditionalInfo=None,
        ChargingStationLocationReference=None,
        OpeningTimes=None,
        IsHubjectCompatible=False,
        DynamicInfoAvailable="false",
        DynamicPowerLevel=None,
        RenewableEnergy=False,
    )


@pytest.fixture
def emsdetten_evse_data_record():
    return EvseDataRecordFactory.build(
        deltaType=None,
        lastUpdate=datetime(2024, 9, 22, 17, 32, 8, 599540, tzinfo=pytz.UTC),
        EvseID="DE*SMP*Eemsdettenevseuid",
        Address=AddressFactory(
            Country="DEU",
            City="Harelbeke",
            Street="Südring",
            PostalCode="38170",
            HouseNum="25",
            Floor="1",
            Region="Flanders",
            ParkingFacility=False,
            ParkingSpot=None,
            TimeZone="UTC+01:00",
        ),
        ChargingStationId=None,
        AccessibilityLocation=None,
        ClearinghouseID=None,
        ChargingStationNames=[InfoTextType(lang="en", value="Berlin Location")],
        HardwareManufacturer=None,
        ChargingStationImage=None,
        SubOperatorName=None,
        GeoChargingPointEntrance=GeoCoordinatesFactory(
            Google=None,
            DegreeMinuteSeconds=None,
            DecimalDegree=DecimalDegree(Longitude="0.000000", Latitude="0.000000"),
        ),
        GeoCoordinates=GeoCoordinatesFactory(
            Google=None,
            DegreeMinuteSeconds=None,
            DecimalDegree=DecimalDegree(Longitude="0.000000", Latitude="0.000000"),
        ),
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
        MaxCapacity=None,
        DynamicPowerLevel=None,
        PaymentOptions=[PaymentOption.Contract],
        ValueAddedServices=[ValueAddedService.None_],
        HotlinePhoneNumber="+3256380211",
        IsHubjectCompatible=False,
        RenewableEnergy=False,
        EnergySource=None,
        DynamicInfoAvailable="false",
        OpeningTimes=None,
        AdditionalInfo=None,
        ChargingStationLocationReference=None,
    )


@pytest.fixture
def evse_full_load_payload(
    berlin_op_evse_data, berlin_evse_data_record, emsdetten_evse_data_record
):
    return ERoamingPushEvseData(
        ActionType=ActionType.fullLoad,
        OperatorEvseData=OperatorEvseData(
            OperatorID=berlin_op_evse_data.OperatorID,
            OperatorName=berlin_op_evse_data.OperatorName,
            EvseDataRecord=[berlin_evse_data_record, emsdetten_evse_data_record],
        ),
    )


@pytest.fixture
def hubject_successful_response():
    return {
        "Result": "true",
        "StatusCode": {
            "Code": "000",
            "Description": "null",
            "AdditionalInfo": "null",
        },
        "SessionID": "null",
        "CPOPartnerSessionID": "null",
        "EMPPartnerSessionID": "null",
    }


@pytest.fixture
def hubject_unsuccessful_response():
    return {
        "message": "Error parsing/validating JSON.",
        "validationErrors": [
            {
                "fieldReference": "operatorEvseData.evseDataRecord[0].valueAddedServices",
                "errorMessage": "must not be empty",
            }
        ],
    }


@pytest.fixture
def operator_fi_cpo():
    return CredentialsRoleFactory(
        country_code="FI",
        party_id="CPO",
        business_details=BusinessDetailsFactory(name="Smappee Pvt Ltd"),
    )


@pytest.fixture
def msp_de_ice():
    return CredentialsRoleFactory(country_code="DE", party_id="ICE")


@pytest.fixture
def smp1_solid_tariff(operator_fi_cpo, msp_de_ice):
    return SolidTariffFactory(
        external_id="SMP1",
        operator=operator_fi_cpo,
        msp=msp_de_ice,
        ocpi_tariff=TariffFactory(uid="OCPITARIFF1"),
    )


@pytest.fixture
def smp2_solid_tariff(operator_fi_cpo, msp_de_ice):
    return SolidTariffFactory(
        external_id="SMP2",
        operator=operator_fi_cpo,
        msp=msp_de_ice,
        ocpi_tariff=TariffFactory(uid="OCPITARIFF2"),
    )


@pytest.fixture
def pricing_products_full_load_payload():
    return ERoamingPushPricingProductDataFactory()


@pytest.fixture
def connector_max_electric_power_10kw():
    return ConnectorFactory(max_electric_power=10000)


@pytest.fixture
def connector_max_electric_power_15kw():
    return ConnectorFactory(max_electric_power=15000)


@pytest.fixture
def connector_max_electric_power_5kw():
    return ConnectorFactory(max_electric_power=5000)


@pytest.fixture
def connector_max_electric_power_none():
    return ConnectorFactory(max_electric_power=None)


@pytest.fixture
def smp1_solid_tariff_with_all_records():
    return SolidTariffFactory(
        external_id="SMP1", ocpi_tariff=TariffFactory(uid="TARIFFNONE")
    )


@pytest.fixture
def smp1_solid_tariff_with_none_prices():
    return SolidTariffFactory(
        external_id="SMP1", price_per_kwh=None, price_per_min=None, price_per_hr=None
    )


@pytest.fixture
def smp1_solid_tariff_without_msp():
    return SolidTariffFactory(external_id="SMP1", msp=None)


@pytest.fixture
def pricing_product_data_record_successful_result():
    return PricingProductDataRecord(
        AdditionalReferences=[
            AdditionalReference(
                AdditionalReference=AdditionalReferenceChoice.START_FEE,
                AdditionalReferenceUnit=ReferenceUnit(
                    root=HubjectPriceComponent.HOUR.value
                ),
                PricePerAdditionalReferenceUnit=Decimal("0.300"),
            ),
            AdditionalReference(
                AdditionalReference=AdditionalReferenceChoice.PARKING_FEE,
                AdditionalReferenceUnit=ReferenceUnit(
                    root=HubjectPriceComponent.HOUR.value
                ),
                PricePerAdditionalReferenceUnit=Decimal("0.300"),
            ),
        ],
        IsValid24hours=True,
        MaximumProductChargingPower=0,
        PricePerReferenceUnit=Decimal("0.200"),
        ProductAvailabilityTimes=[],
        ProductID=ProductID(root="TARIFFNONE*SMP1"),
        ProductPriceCurrency=CurrencyID(root="EUR"),
        ReferenceUnit=ReferenceUnit(root="KILOWATT_HOUR"),
    )


@pytest.fixture
def pricing_product_data_successful_result():
    return PricingProductData(
        OperatorID=OperatorID(root="FI*CPO"),
        OperatorName="Smappee eRoam CPO",
        ProviderID=ProviderIDAsterisk(root="*"),
        PricingDefaultPrice=0.3,
        PricingDefaultPriceCurrency=CurrencyID(root="EUR"),
        PricingDefaultReferenceUnit=ReferenceUnit(root="HOUR"),
        PricingProductDataRecords=[
            PricingProductDataRecord(
                ProductID=ProductID(root="TARIFFNONE*SMP1"),
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
        ],
    )


@pytest.fixture
def session_for_cdr():
    cdr_token = CdrTokenFactory(uid="BAADF00D")

    return OCPISessionFactory(
        uid="SESSION123",
        cdr_token=cdr_token,
    )


@pytest.fixture
def ocpi_cdr(session_for_cdr):
    cdr_location = CdrLocationFactory(
        evse_uid="EVSECONVERT", evse_id="FI*CPO*EEVSECONVERT"
    )
    cdr = CdrFactory(session_id=session_for_cdr.uid, cdr_location=cdr_location)

    return cdr


@pytest.fixture
def expected_eroaming_cdr():
    return {
        "CPOPartnerSessionID": "SESSION123",
        "CalibrationLawVerificationInfo": None,
        "ChargingEnd": "2022-02-22T23:22:22Z",
        "ChargingStart": "2022-02-22T22:22:22Z",
        "ConsumedEnergy": 120.0,
        "EMPPartnerSessionID": "EMSPSESSION1",
        "EvseID": "FI*CPO*EEVSECONVERT",
        "HubOperatorID": "FI*CPO",
        "HubProviderID": "FI*MSP",
        "Identification": {
            "RFIDMifareFamilyIdentification": {"UID": "BAADF00D"},
            "RemoteIdentification": None,
            "QRCodeIdentification": None,
            "RFIDIdentification": None,
            "PlugAndChargeIdentification": None,
        },
        "MeterValueEnd": 120.0,
        "MeterValueInBetween": None,
        "MeterValueStart": 0.0,
        "PartnerProductID": None,
        "SessionEnd": "2022-02-22T23:22:22Z",
        "SessionID": "b2688855-7f00-0002-6d8e-48d883f6abb6",
        "SessionStart": "2022-02-22T22:22:22Z",
        "SignedMeteringValues": None,
    }


@pytest.fixture
def remote_command_payload():
    evse = EvseFactory(status="AVAILABLE")
    ConnectorFactory(evse=evse)

    return {
        "Identification": {"RemoteIdentification": {"EvcoID": "DE-DCB-C12345678-X"}},
        "CPOPartnerSessionID": "",
        "EMPPartnerSessionID": "2345ABC",
        "ProviderID": "DE-DCB",
        "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
        "PartnerProductID": "AC1",
        "EvseID": f"{evse.location.ocpi_master.country_code}*{evse.location.ocpi_master.party_id}*E{evse.uid}",
    }


@pytest.fixture
def remote_stop_command_payload():
    evse = EvseFactory(status="CHARGING")

    return {
        "CPOPartnerSessionID": "",
        "EMPPartnerSessionID": "2345ABC",
        "ProviderID": "DE-DCB",
        "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
        "EvseID": f"{evse.location.ocpi_master.country_code}*{evse.location.ocpi_master.party_id}*E{evse.uid}",
    }


@pytest.fixture
def remote_stop_session():
    evse = EvseFactory(status="CHARGING")

    return OCPISessionFactory(
        uid="OURSESSIONID", evse=evse, authorization_reference="2345ABC"
    )


@pytest.fixture
def sample_evse_data_payload():
    return ERoamingPushEvseData(
        ActionType=ActionType.fullLoad,
        OperatorEvseData=OperatorEvseData(
            OperatorID=OperatorID(root="DE*BER"),
            OperatorName="MNO Company Pvt Ltd",
            EvseDataRecord=[
                EvseDataRecord(
                    EvseID=EvseID(root="DE*BER*EMNOEVSEUID"),
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Test Station 1")
                    ],
                    Address=Address(
                        Country="DEU",
                        City="Berlin",
                        Street="Test Street",
                        PostalCode="10115",
                        HouseNum="1",
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        DecimalDegree=DecimalDegree(
                            Longitude="13.404954", Latitude="52.520008"
                        ),
                        Google=None,
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.AC_3_PHASE,
                            Voltage=230,
                            Amperage=16,
                            Power=11,
                        )
                    ],
                    AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.None_],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    HotlinePhoneNumber="+491234567890",
                    IsOpen24Hours=True,
                    IsHubjectCompatible=True,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                    RenewableEnergy=False,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AccessibilityLocation=None,
                    OpeningTimes=None,
                ),
                EvseDataRecord(
                    EvseID=EvseID(root="DE*BER*ESECONDUID"),
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Test Station 2")
                    ],
                    Address=Address(
                        Country="DEU",
                        City="Berlin",
                        Street="Another Street",
                        PostalCode="10115",
                        HouseNum="2",
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        DecimalDegree=DecimalDegree(
                            Longitude="13.404954", Latitude="52.520008"
                        ),
                        Google=None,
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.DC, Voltage=400, Amperage=125, Power=50
                        )
                    ],
                    AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.Reservation],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    HotlinePhoneNumber="+491234567890",
                    IsOpen24Hours=True,
                    IsHubjectCompatible=True,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                    RenewableEnergy=False,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AccessibilityLocation=None,
                    OpeningTimes=None,
                ),
            ],
        ),
    )
