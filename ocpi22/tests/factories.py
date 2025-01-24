import random
import time
from zoneinfo import ZoneInfo

import factory
import pytz
from faker import Faker

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
    ActionType,
    Accessibility,
    ERoamingPushPricingProductData,
    PricingProductData,
    PricingProductDataRecord,
)
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import CredentialsRole, Credentials
from ocpi22.models.image import OCPIImageCategory, OCPIImage
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff, SolidTariff

fake = Faker()


class OCPIImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OCPIImage

    url = "https://example.com/image.jpg"
    thumbnail = "https://example.com/thumbnail.jpg"
    category = OCPIImageCategory.OPERATOR
    image_type = "jpeg"
    width = 800
    height = 600


class BusinessDetailsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BusinessDetails

    name = factory.Faker("company")
    website = factory.Faker("url")
    logo = factory.SubFactory(OCPIImageFactory)


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
    valid = True


class CredentialsRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CredentialsRole

    role = "CPO"
    business_details = factory.SubFactory(BusinessDetailsFactory)
    country_code = "FI"
    party_id = "CPO"
    credentials = factory.SubFactory(CredentialsFactory)


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    uid = factory.Faker("uuid4")
    publish = True
    name = "Location A"
    address = "Alfred Nobellaan 22 App 150Z"
    city = "Harelbeke"
    postal_code = "8530"
    state = ""
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


class EvseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Evse

    uid = f"{int(time.time())}"
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
    tariff_alt_url = "https://smappee.com/tariffs/"
    min_price_excl_vat = 0.1
    min_price_incl_vat = 0.2
    max_price_excl_vat = 0.8
    max_price_incl_vat = 0.9
    ocpi_master = factory.SubFactory(CredentialsRoleFactory)

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
    terms_and_conditions = "https://smappee.com/terms-and-conditions/"
    last_updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    updated = factory.Faker("date_time", tzinfo=pytz.UTC)
    created = factory.Faker("date_time", tzinfo=pytz.UTC)

    @factory.post_generation
    def tariff_ids(self, create, extracted, **kwargs):
        if not create:
            # Skip if the instance is not saved to the database
            return

        if extracted:
            # Add the provided Tariffs
            for tariff in extracted:
                self.tariff_ids.add(tariff)
        else:
            # Add a default Tariff if none are provided
            self.tariff_ids.add(TariffFactory())


class AddressFactory(factory.Factory):
    class Meta:
        model = Address

    Country = "BEL"
    City = "Harelbeke"
    Street = "Evolis"
    PostalCode = "8530"
    HouseNum = "104"
    Floor = "1"
    Region = "Flanders"
    ParkingFacility = True
    ParkingSpot = "Parking Spot1"
    TimeZone = "UTC+01:00"


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

    PowerType = PowerType.AC_1_PHASE
    Voltage = 225
    Amperage = 50
    Power = 900
    ChargingMode = [ChargingMode.Mode_1]


class EvseDataRecordFactory(factory.Factory):
    class Meta:
        model = EvseDataRecord

    deltaType = DeltaType.update
    lastUpdate = factory.Faker("date_time", tzinfo=pytz.UTC)
    EvseID = factory.Faker("uuid4")
    ChargingPoolID = None
    ChargingStationId = ""
    ChargingStationNames = []
    HardwareManufacturer = ""
    ChargingStationImage = ""
    SubOperatorName = ""
    Address = factory.SubFactory("ocpi22.tests.factories.AddressFactory")
    GeoCoordinates = factory.SubFactory("ocpi22.tests.factories.GeoCoordinatesFactory")
    Plugs = [Plug.Type_2_Outlet]
    DynamicPowerLevel = True
    ChargingFacilities = factory.List(
        [
            factory.SubFactory("ocpi22.tests.factories.ChargingFacilityFactory")
            for _ in range(3)
        ]
    )
    RenewableEnergy = True
    EnergySource = []
    EnvironmentalImpact = None
    CalibrationLawDataAvailability = (CalibrationLawDataAvailability.Local,)
    AuthenticationModes = [AuthenticationMode.NFC_RFID_Classic]
    MaxCapacity = 950
    PaymentOptions = [PaymentOption.Direct]
    ValueAddedServices = [ValueAddedService.Reservation]
    Accessibility = Accessibility.Free_publicly_accessible
    AccessibilityLocation = AccessibilityLocation.OnStreet
    HotlinePhoneNumber = "+3256380211"
    AdditionalInfo = []
    ChargingStationLocationReference = []
    GeoChargingPointEntrance = factory.SubFactory(
        "ocpi22.tests.factories.GeoCoordinatesFactory"
    )
    IsOpen24Hours = True
    OpeningTimes = []
    HubOperatorID = None
    ClearinghouseID = "Clearing house ID 1"
    IsHubjectCompatible = True
    DynamicInfoAvailable = DynamicInfoAvailable.auto


class OperatorEvseDataFactory(factory.Factory):
    class Meta:
        model = OperatorEvseData

    OperatorID = "DE*SMP"
    OperatorName = "Smappee Operator"
    EvseDataRecord = factory.List(
        [
            factory.SubFactory("ocpi22.tests.factories.EvseDataRecordFactory")
            for _ in range(3)
        ]
    )


class ERoamingPushEvseDataFactory(factory.Factory):
    class Meta:
        model = ERoamingPushEvseData

    ActionType = ActionType.fullLoad
    OperatorEvseData = factory.SubFactory(
        "ocpi22.tests.factories.OperatorEvseDataFactory"
    )


class PricingProductDataRecordFactory(factory.Factory):
    class Meta:
        model = PricingProductDataRecord

    ProductID = "UNIQUE_TARIFF_ID"
    ReferenceUnit = "MINUTE"
    ProductPriceCurrency = "EUR"
    PricePerReferenceUnit = 0.43
    MaximumProductChargingPower = 1000
    IsValid24hours = True
    ProductAvailabilityTimes = []
    AdditionalReferences = []


class PricingProductDataFactory(factory.Factory):
    class Meta:
        model = PricingProductData

    OperatorID = "BE*SMP"
    OperatorName = "Smappee eRoam CPO"
    ProviderID = "DE*ICE"
    PricingDefaultPrice = 0.43
    PricingDefaultPriceCurrency = "EUR"
    PricingDefaultReferenceUnit = "MINUTE"
    PricingProductDataRecords = factory.List(
        [factory.SubFactory("ocpi22.tests.factories.PricingProductDataRecordFactory")]
    )


class ERoamingPushPricingProductDataFactory(factory.Factory):
    class Meta:
        model = ERoamingPushPricingProductData

    ActionType = ActionType.fullLoad
    PricingProductData = factory.SubFactory(
        "ocpi22.tests.factories.PricingProductDataFactory"
    )


class SolidTariffFactory(factory.Factory):
    class Meta:
        model = SolidTariff

    external_id = f"SD{int(time.time())}"
    currency = "EUR"
    price_per_kwh = 0.2
    price_per_min = 0.3
    price_flat = 0.3
    vat_percentage = 0.2
    archived = False
    msp = factory.SubFactory("ocpi22.tests.factories.CredentialsRoleFactory")
    operator = factory.SubFactory("ocpi22.tests.factories.CredentialsRoleFactory")

    last_updated_at = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
    created_at = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
