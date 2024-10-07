import random

import factory
import pytz

from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    OperatorEvseData,
    EvseDataRecord,
    DeltaType,
    DynamicInfoAvailable,
    CalibrationLawDataAvailability,
    Plug,
    Address,
    GeoCoordinates,
    Google,
    DecimalDegree,
    DegreeMinuteSeconds,
    ChargingFacility,
    PowerType,
    ChargingMode,
    AuthenticationMode,
    PaymentOption,
    ValueAddedService,
    AccessibilityLocation,
)
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.credentials import CredentialsRole, Credentials
from ocpi22.models.tariff import Tariff


class BusinessDetailsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BusinessDetails

    name = factory.Faker("company")
    website = factory.Faker("url")
    logo = factory.Faker("image_url")


class CredentialsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Credentials

    token_a = factory.Faker("uuid4")
    ours = factory.Faker("uuid4")
    theirs = factory.Faker("uuid4")
    url = factory.Faker("url")
    connection_status = "CONNECTED"
    last_connection = factory.Faker("date_time", tzinfo=pytz.UTC)
    version = "22"
    valid = factory.Faker("boolean")


class CredentialsRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CredentialsRole

    role = "CPO"
    business_details = factory.SubFactory(BusinessDetailsFactory)
    country_code = "AW"
    party_id = "ABC"
    credentials = factory.SubFactory(CredentialsFactory)


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    uid = factory.Faker("uuid4")
    publish = factory.Faker("boolean")
    name = factory.Faker("company")
    address = "Alfred Nobellaan 22 App 150Z"
    city = factory.Faker("city")
    postal_code = factory.Faker("postcode")
    state = factory.Faker("state")
    country = "FIN"
    latitude = factory.LazyAttribute(
        lambda x: round(random.uniform(-90, 90), random.randint(1, 6))
    )
    longitude = factory.LazyAttribute(
        lambda x: round(random.uniform(-180, 180), random.randint(1, 6))
    )
    time_zone = "Europe/Helsinki"
    ocpi_master = factory.SubFactory(CredentialsRoleFactory)
    operator = factory.SubFactory(BusinessDetailsFactory)
    suboperator = factory.SubFactory(BusinessDetailsFactory)
    owner = factory.SubFactory(BusinessDetailsFactory)
    charging_when_closed = factory.Faker("boolean")
    parking_type = "ON_STREET"
    evses = factory.RelatedFactoryList(
        "ocpi22.tests.factories.EvseFactory", "location", size=3
    )


class EvseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Evse

    uid = factory.Faker("uuid4")
    evse_id = "FI*ABC*E1234*5678"
    status = "RESERVED"
    location = factory.SubFactory(LocationFactory)
    last_updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    created = factory.Faker("date_time", tzinfo=pytz.UTC)
    capabilities = ["RFID_READER", "RESERVABLE"]


class TariffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tariff

    uid = factory.Faker("uuid4")
    currency = "EUR"
    type = "AD_HOC_PAYMENT"
    tariff_alt_url = factory.Faker("url")
    min_price_excl_vat = factory.Faker("Float", positive=True)
    min_price_incl_vat = factory.Faker("Float", positive=True)
    max_price_excl_vat = factory.Faker("Float", positive=True)
    max_price_incl_vat = factory.Faker("Float", positive=True)

    last_updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    created = factory.Faker("date_time", tzinfo=pytz.UTC)


class ConnectorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Connector

    uid = factory.Faker("uuid4")
    evse = factory.SubFactory(EvseFactory)
    standard = "IEC_62196_T2"
    format = "CABLE"
    power_type = ["AC_3_PHASE"]
    max_voltage = 400
    max_amperage = 32
    max_electric_power = 22
    terms_and_conditions = factory.Faker("url")
    last_updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    created = factory.Faker("date_time", tzinfo=pytz.UTC)


class AddressFactory(factory.Factory):
    class Meta:
        model = Address

    Country = factory.Faker("country_code", representation="alpha-3")
    City = factory.Faker("city")
    Street = factory.Faker("street_address")
    PostalCode = factory.Faker("postcode")
    HouseNum = "1"
    Floor = "2"
    Region = factory.Faker("state")
    ParkingFacility = factory.Faker("boolean")
    ParkingSpot = factory.Faker("word")
    TimeZone = "UTC-05:00"


class GoogleFactory(factory.Factory):
    class Meta:
        model = Google

    Coordinates = "47.662249 9.360922"


class DecimalDegreeFactory(factory.Factory):
    class Meta:
        model = DecimalDegree

    Longitude = "47.662249"
    Latitude = "9.360922"


class DegreeMinuteSecondsFactory(factory.Factory):
    class Meta:
        model = DegreeMinuteSeconds

    Longitude = "9°21'39.32''"
    Latitude = "9°21'39.32''"


class GeoCoordinatesFactory(factory.Factory):
    class Meta:
        model = GeoCoordinates

    Google = factory.SubFactory("ocpi22.tests.factories.GoogleFactory")
    DecimalDegree = factory.SubFactory("ocpi22.tests.factories.DecimalDegreeFactory")
    DegreeMinuteSeconds = factory.SubFactory(
        "ocpi22.tests.factories.DegreeMinuteSecondsFactory"
    )


class ChargingFacilityFactory(factory.Factory):
    class Meta:
        model = ChargingFacility

    PowerType = factory.Faker(
        "random_element",
        elements=[PowerType.AC_1_PHASE, PowerType.DC, PowerType.AC_3_PHASE],
    )
    Voltage = factory.Faker("random_int", min=0, max=999)
    Amperage = factory.Faker("random_int", min=0, max=999)
    Power = factory.Faker("random_int", min=0, max=999)
    ChargingMode = ChargingMode.Mode_1


class EvseDataRecordFactory(factory.Factory):
    class Meta:
        model = EvseDataRecord

    deltaType = factory.Faker(
        "random_element",
        elements=[DeltaType.update, DeltaType.insert, DeltaType.delete],
    )
    lastUpdate = factory.Faker("date_time", tzinfo=pytz.UTC)
    EvseID = factory.Faker("uuid4")
    ChargingPoolID = ""
    ChargingStationId = ""
    ChargingStationNames = []
    HardwareManufacturer = ""
    ChargingStationImage = ""
    SubOperatorName = ""
    Address = factory.SubFactory("ocpi22.tests.factories.AddressFactory")
    GeoCoordinates = factory.SubFactory("ocpi22.tests.factories.GeoCoordinatesFactory")
    Plugs = Plug.Type_2_Outlet
    DynamicPowerLevel = factory.Faker("boolean")
    ChargingFacilities = factory.List(
        [
            factory.SubFactory("ocpi22.tests.factories.ChargingFacilityFactory")
            for _ in range(3)
        ]
    )
    RenewableEnergy = factory.Faker("boolean")
    EnergySource = []
    EnvironmentalImpact = None
    CalibrationLawDataAvailability = factory.Faker(
        "random_element",
        elements=[
            CalibrationLawDataAvailability.Local,
            CalibrationLawDataAvailability.External,
            CalibrationLawDataAvailability.Not_Available,
        ],
    )
    AuthenticationModes = [AuthenticationMode.NFC_RFID_Classic]
    MaxCapacity = factory.Faker("random_int", min=0, max=999)
    PaymentOptions = [PaymentOption.Direct]
    ValueAddedServices = [ValueAddedService.Reservation]
    Accessibility = []
    AccessibilityLocation = AccessibilityLocation.OnStreet
    HotlinePhoneNumber = factory.Faker("phone_number")
    AdditionalInfo = []
    ChargingStationLocationReference = []
    GeoChargingPointEntrance = factory.SubFactory(
        "ocpi22.tests.factories.GeoCoordinatesFactory"
    )
    IsOpen24Hours = factory.Faker("boolean")
    OpeningTimes = []
    HubOperatorID = None
    ClearinghouseID = factory.Faker("uuid4")
    IsHubjectCompatible = factory.Faker("boolean")
    DynamicInfoAvailable = factory.Faker(
        "random_element",
        elements=[
            DynamicInfoAvailable.true,
            DynamicInfoAvailable.false,
            DynamicInfoAvailable.auto,
        ],
    )


class OperatorEvseDataFactory(factory.Factory):
    class Meta:
        model = OperatorEvseData

    OperatorID = "DE*SMP"
    OperatorName = factory.Faker("company")
    EvseDataRecord = factory.List(
        [factory.SubFactory("ocpi22.tests.factories.EvseFactory") for _ in range(3)]
    )


class ERoamingPushEvseDataFactory(factory.Factory):
    class Meta:
        model = ERoamingPushEvseData

    ActionType = "update"
    OperatorEvseData = factory.SubFactory(
        "ocpi22.tests.factories.OperatorEvseDataFactory"
    )
