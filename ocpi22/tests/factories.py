import random

import factory
import pytz

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
