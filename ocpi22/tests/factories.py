import time
import uuid
from datetime import datetime
from datetime import time as datetime_time
from decimal import Decimal
from zoneinfo import ZoneInfo

import factory
import pytz
from django.contrib.auth.models import User
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
    ERoamingPushEVSEPricing,
    EVSEPricingItem,
)
from ocpi22.choices import EndpointRoleEnum, OcpiModuleEnum, CdrDimensionEnum
from ocpi22.commands.models import CallBacks, CallBackExecutionStatus
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.cdrtoken import CdrToken
from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import CredentialsRole, Credentials, Endpoint
from ocpi22.models.image import OCPIImageCategory, OCPIImage
from ocpi22.models.hours import RegularHours
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session, CdrDimension, ChargingPeriod
from ocpi22.models.tariff import (
    Tariff,
    SolidTariff,
    TariffElement,
    PriceComponent,
    DefaultTariffs,
)
from ocpi22.models.token import Token
from ocpi22.ocpi.util import Ocpi

fake = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"SolidRoamUser{n}")
    email = "user@solidroam.com"
    password = factory.PostGenerationMethodCall(
        "set_password", "j0s9J117uS126dNr915zIj7d1J10UJ2f"
    )


class StaffUserFactory(UserFactory):
    is_staff = True


class SuperUserFactory(UserFactory):
    is_superuser = True
    is_staff = True


class OCPIImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OCPIImage

    url = "https://localhost/image.jpg"
    thumbnail = "https://localhost/thumbnail.jpg"
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
    meter_value_frequency = 300
    allowed_locations = []
    auth_priority = 0


class CredentialsRoleFactoryWithoutCredentials(factory.django.DjangoModelFactory):
    class Meta:
        model = CredentialsRole

    role = "CPO"
    business_details = factory.SubFactory(BusinessDetailsFactory)
    country_code = "FI"
    party_id = "CPO"


class CredentialsRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CredentialsRole

    role = "CPO"
    business_details = factory.SubFactory(BusinessDetailsFactory)
    country_code = "FI"
    party_id = "CPO"
    credentials = factory.SubFactory(CredentialsFactory)

    @factory.post_generation
    def add_endpoints(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for endpoint in extracted:
                EndpointFactory(credentials_role=self, **endpoint)
        else:
            for endpoint in OcpiModuleEnum:
                EndpointFactory(
                    credentials=self.credentials,
                    identifier=endpoint.value,
                    role=EndpointRoleEnum.SENDER.value,
                    url=f"https://localhost/ocpi/{endpoint.value.lower()}",
                )
                EndpointFactory(
                    credentials=self.credentials,
                    identifier=endpoint.value,
                    role=EndpointRoleEnum.RECEIVER.value,
                    url=f"https://localhost/ocpi/{endpoint.value.lower()}",
                )


class EndpointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Endpoint

    url = "http://localhost/ocpi/some/endpoint/"


class RegularHoursFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegularHours

    weekday = 1
    period_begin = datetime_time(0, 0)
    period_end = datetime_time(0, 0)


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
    latitude = "47.662249"
    longitude = "9.360922"
    time_zone = "Europe/Helsinki"
    ocpi_master = factory.SubFactory(CredentialsRoleFactory)
    operator = factory.SubFactory(BusinessDetailsFactory)
    suboperator = factory.SubFactory(BusinessDetailsFactory)
    owner = factory.SubFactory(BusinessDetailsFactory)
    charging_when_closed = factory.Faker("boolean")
    parking_type = "ON_STREET"
    roaming_enabled = True


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


class TariffElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TariffElement


class PriceComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PriceComponent

    type = "ENERGY"
    step_size = 1
    price = 0.4
    vat = 20


class TariffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tariff

    @factory.post_generation
    def build_tariff(self, create, extracted, **kwargs):
        if not create:
            return

        def add_price_components(tariff_element):
            PriceComponentFactory(tariff_element=tariff_element)
            PriceComponentFactory(
                tariff_element=tariff_element, type="TIME", price=0.3, step_size=1
            )

        if extracted:
            for tariffelement in extracted:
                te = TariffElementFactory(tariff=self, **tariffelement)
                add_price_components(te)
        else:
            te = TariffElementFactory(tariff=self)
            add_price_components(te)

    uid = factory.Faker("uuid4")
    currency = "EUR"
    type = "AD_HOC_PAYMENT"
    tariff_alt_url = "https://solidroam.com/tariffs/"
    min_price_excl_vat = 0.1
    min_price_incl_vat = 0.2
    max_price_excl_vat = 0.8
    max_price_incl_vat = 0.9
    ocpi_master = factory.SubFactory(
        CredentialsRoleFactory, role="CPO", country_code="FI", party_id="MSP"
    )

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
    power_type = "AC_3_PHASE"
    max_voltage = 400
    max_amperage = 32
    max_electric_power = 22
    terms_and_conditions = "https://localhost/terms-and-conditions/"
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


class EvsePricingItemFactory(factory.Factory):
    class Meta:
        model = EVSEPricingItem

    EvseID = "BE*SMP*ESDEVSEID"
    ProviderID = "DE*SMP"
    EvseIDProductList = ["SMP1"]


class ERoamingPushEVSEPricingFactory(factory.Factory):
    class Meta:
        model = ERoamingPushEVSEPricing

    ActionType = ActionType.fullLoad
    EVSEPricing = factory.List(
        [factory.SubFactory("ocpi22.tests.factories.EvsePricingItemFactory")]
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


class SolidTariffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SolidTariff

    external_id = f"SD{int(time.time())}"
    currency = "EUR"
    price_per_kwh = Decimal("0.2")
    price_per_min = Decimal("0.3")
    price_per_hr = Decimal("0.3")
    parking_price_per_min = Decimal("0.1")
    parking_price_per_hr = Decimal("0.2")
    price_flat = Decimal("0.3")
    vat_percentage = 0.2
    msp = factory.SubFactory(
        CredentialsRoleFactory, role="EMSP", country_code="DE", party_id="ICE"
    )
    operator = factory.SubFactory(
        CredentialsRoleFactory, role="CPO", country_code="FI", party_id="MSP"
    )
    ocpi_tariff = factory.SubFactory(TariffFactory)

    last_updated = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
    created_at = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))


class CdrFactory(factory.Factory):
    class Meta:
        model = Cdr

    @factory.post_generation
    def set_tariffs(self, create, extracted, **kwargs):
        if not create:
            # Skip if the instance is not saved to the database
            return

        # Ensure the instance is saved before setting M2M relationships
        if self.pk is None:
            self.save()

        if extracted:
            # Add the provided tariffs
            for tariff in extracted:
                self.tariffs.add(tariff)
        else:
            # Add a default Tariff if none are provided
            self.tariffs.add(TariffFactory())

    ocpi_master = factory.SubFactory(CredentialsRoleFactory)
    uid = "UID12345"
    start_date_time = datetime(2022, 2, 22, 22, 22, 22, tzinfo=pytz.UTC)
    end_date_time = datetime(2022, 2, 22, 23, 22, 22, tzinfo=pytz.UTC)
    session_id = "SESSION123"
    cdr_token_uid = "TOKEN123"
    cdr_token_type = "RFID"
    cdr_token_contract_id = "CONTRACT-123"
    auth_method = "WHITELIST"
    authorization_reference = "AUTH-123"
    cdr_location_uid = "LOC-123"
    cdr_location_address = "Alfred Nobellaan 22 App 150Z"
    cdr_location_city = "Harelbeke"
    cdr_location_postal_code = "8530"
    cdr_location_country = "BEL"
    cdr_location_latitude = "47.662249"
    cdr_location_longitude = "9.360922"
    cdr_location_name = "Location A"
    cdr_location_evse_uid = "EVSE123"
    cdr_location_evse_id = factory.LazyAttribute(
        lambda obj: f"{obj.ocpi_master.country_code}*{obj.ocpi_master.party_id}*E{obj.cdr_location_evse_uid}"[
            :48
        ]
    )
    cdr_location_connector_id = "1"
    cdr_location_connector_standard = "IEC_62196_T2"
    cdr_location_connector_format = "CABLE"
    cdr_location_connector_power_type = "AC_3_PHASE"
    currency = "EUR"
    total_cost_excl_vat = 0.1
    total_cost_incl_vat = 0.2
    total_energy = 120.0
    billed_to = factory.SubFactory(
        CredentialsRoleFactory, role="EMSP", country_code="FI", party_id="MSP"
    )
    last_updated = datetime(2022, 2, 22, 23, 22, 22, tzinfo=pytz.UTC)


class CdrTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CdrToken

    ocpi_master = factory.SubFactory(
        CredentialsRoleFactory,
        party_id="MSP",
        role="EMSP",
        business_details__name="Test MSP",
    )
    uid = "DEADC0DE"
    token_type = "RFID"
    contract_id = "CONTRACT-12345"


class CdrLocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CdrLocation

    uid = "LOC12345"
    name = "Location A"
    address = "Alfred Nobellaan 22 App 150Z"
    city = "Harelbeke"
    postal_code = "8530"
    state = ""
    country = "BEL"
    latitude = "47.662249"
    longitude = "9.360922"
    evse_uid = "12345"
    evse_id = "FI*MSP*E12345"
    connector_id = "1"
    connector_standard = "IEC_62196_T2"
    connector_format = "CABLE"
    connector_power_type = "AC_3_PHASE"


class OCPISessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Session

    ocpi_master = factory.SubFactory(
        CredentialsRoleFactory,
        party_id="CPO",
        role="CPO",
        business_details__name="Test CPO",
    )
    uid = str(uuid.uuid4())
    reservation_id = "EMSPSESSION1"
    hub_session_id = "b2688855-7f00-0002-6d8e-48d883f6abb6"
    start_date_time = datetime(2021, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
    end_date_time = datetime(2021, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
    start_kwh = 0.0
    stop_kwh = 120.0
    cdr_token = factory.SubFactory(CdrTokenFactory)
    billed_to = factory.LazyAttribute(lambda obj: obj.cdr_token.ocpi_master)
    auth_method = "AUTH_REQUEST"
    authorization_reference = "AUTHORIZATION-12345"
    connector = factory.SubFactory(ConnectorFactory)
    evse = factory.LazyAttribute(lambda obj: obj.connector.evse)
    location = factory.LazyAttribute(lambda obj: obj.connector.evse.location)
    currency = "EUR"
    total_cost_excl_vat = 10.0
    total_cost_incl_vat = 12.0
    status = Session.ACTIVE
    last_updated = datetime(2021, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
    credentials = factory.LazyAttribute(lambda obj: obj.ocpi_master.credentials)


class TokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Token

    ocpi_master = factory.SubFactory(CredentialsRoleFactory)
    uid = "TOKEN1"
    type = "RFID"
    contract_id = factory.Faker("uuid4")
    visual_number = "045736789864"
    issuer = factory.Faker("company")
    group_id = factory.Faker("uuid4")
    valid = True
    whitelist = Token.ALLOWED
    language = "EN"
    default_profile_type = "REGULAR"
    last_updated = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
    updated = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
    created = factory.Faker("date_time", tzinfo=ZoneInfo("UTC"))
    customer = factory.SubFactory(UserFactory)


class CdrDimensionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CdrDimension

    type = CdrDimensionEnum.ENERGY.value
    volume = 10.0


class ChargingPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChargingPeriod

    start_date_time = factory.LazyFunction(lambda: datetime.now(pytz.UTC))
    session = factory.SubFactory(OCPISessionFactory)
    tariff = factory.SubFactory(TariffFactory)

    @factory.post_generation
    def dimensions(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for dimension in extracted:
                self.dimensions.add(dimension)
        else:
            CdrDimensionFactory(
                chargingperiod=self, type=CdrDimensionEnum.ENERGY.value, volume=10.0
            )
            CdrDimensionFactory(
                chargingperiod=self, type=CdrDimensionEnum.TIME.value, volume=1.5
            )

    @classmethod
    def create_with_dimensions(cls, energy_volume=10.0, time_volume=1.5, **kwargs):
        period = cls.create(**kwargs)

        CdrDimensionFactory(
            chargingperiod=period,
            type=CdrDimensionEnum.ENERGY.value,
            volume=energy_volume,
        )

        CdrDimensionFactory(
            chargingperiod=period, type=CdrDimensionEnum.TIME.value, volume=time_volume
        )

        return period


class DefaultTariffsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DefaultTariffs

    standard = factory.LazyFunction(Ocpi.STANDARD_CHOICES[0][0])

    @factory.post_generation
    def tariffs(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for tariff in extracted:
                self.tariffs.add(tariff)
        else:
            tariff1 = TariffFactory()
            self.tariffs.add(tariff1)


class CallBackFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CallBacks

    session = factory.SubFactory(OCPISessionFactory)
    callback_url = "https://example.com/callback"
    authorization_reference = factory.Faker("uuid4")
    execution_status = CallBackExecutionStatus.PENDING
    response_status_code = None
    response_body = None
    executed_at = None


class TerminalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Terminal

    terminal_id = factory.Sequence(lambda n: f"TERM-{n:05d}")
    customer_reference = "TEST-CUSTOMER-REF"
    # party_id = "PAY"
    # country_code = "NL"
    address = "Keizersgracht 100"
    city = "Amsterdam"
    postal_code = "1015AA"
    country = "NLD"
    invoice_creator = "PTP"
    credentials = factory.SubFactory(CredentialsFactory)
    last_updated = factory.LazyFunction(
        lambda: datetime(2025, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    )


class FinancialAdviceConfirmationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FinancialAdviceConfirmation

    fac_id = factory.Sequence(lambda n: f"FAC-{n:05d}")
    authorization_reference = factory.Sequence(lambda n: f"AUTH-REF-{n:05d}")
    total_cost_excl_vat = 10.0
    total_cost_incl_vat = 12.4
    currency = "EUR"
    eft_data = factory.LazyFunction(lambda: ["EFT-DATA-001", "EFT-DATA-002"])
    capture_status_code = "SUCCESS"
    capture_status_message = None
    last_updated = factory.LazyFunction(
        lambda: datetime(2025, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    )
    credentials = factory.SubFactory(CredentialsFactory)
    terminal = factory.SubFactory(TerminalFactory)
