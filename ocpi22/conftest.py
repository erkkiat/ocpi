from datetime import datetime

import pytest
import pytz

from ocpi22.cpo.schemas import LocationIn, GeoLocation, EVSE, Connector as ConnectorIn
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.models.session import Session
from ocpi22.test_tariff_location_and_evse import load_example
from ocpi22.tests.factories import (
    OCPISessionFactory,
    TariffFactory,
    SolidTariffFactory,
    CredentialsRoleFactory,
)


def create_ocpi_session_with_tariff() -> Session:
    session: Session = OCPISessionFactory(start_kwh=100)
    tariff = TariffFactory(uid="D9931A36-49A3-4C22-BA87-0E3C1792887B")
    session.connector.tariff_ids.set([tariff])
    return session


@pytest.fixture
def completed_session(msp_credentials_with_endpoints) -> Session:
    session = create_ocpi_session_with_tariff()
    session.status = Session.COMPLETED
    session.save()
    return session


@pytest.fixture
def ocpi_master():
    get_our_credentialsrole.cache_clear()
    get_credentialsrole.cache_clear()

    return CredentialsRoleFactory(country_code="FI", party_id="CPO")


@pytest.fixture
def tariffs(ocpi_master):
    t11 = TariffFactory(uid="OCPI_TARIFF_11", ocpi_master=ocpi_master)
    t12 = TariffFactory(uid="OCPI_TARIFF_12", ocpi_master=ocpi_master)
    t13 = TariffFactory(uid="OCPI_TARIFF_13", ocpi_master=ocpi_master)

    SolidTariffFactory(
        external_id="11", operator=ocpi_master, msp=None, ocpi_tariff=t11
    )
    SolidTariffFactory(
        external_id="12", operator=ocpi_master, msp=None, ocpi_tariff=t12
    )
    SolidTariffFactory(
        external_id="13", operator=ocpi_master, msp=None, ocpi_tariff=t13
    )


@pytest.fixture()
def connector_in():
    connector = ConnectorIn(
        id="1",
        standard="IEC_62196_T2",
        format="SOCKET",
        power_type="AC_3_PHASE",
        max_voltage=400,
        max_amperage=32,
        last_updated=datetime.now(pytz.utc),
        tariff_ids=["11", "12"],
    )
    return connector


@pytest.fixture()
def rome_location_in(connector_in):
    evse = EVSE(
        uid="ROME01EVSE01",
        evse_id="FI*CPO*EROME01EVSE01",
        status="AVAILABLE",
        connectors=[],
        last_updated=datetime.now(pytz.utc),
    )

    evse.connectors.append(connector_in)

    location = LocationIn(
        country_code="IT",
        party_id="CPO",
        id="ROME01",
        publish=True,
        address="Via del Corso 123",
        city="Rome",
        postal_code="00100",
        country="ITA",
        coordinates=GeoLocation(latitude=41.9028, longitude=12.4964),
        evses=[],
        last_updated=datetime.now(pytz.utc),
        time_zone="Europe/Rome",
        roaming_enabled=True,
    )
    location.evses.append(evse)

    return location


@pytest.fixture
def location_example(ocpi_master):
    data = load_example("data/examples/location_example.json")
    data.update(
        {
            "country_code": ocpi_master.country_code,
            "party_id": ocpi_master.party_id,
            "roaming_enabled": True,
        }
    )

    data["evses"][0].update({"capabilities": ["RFID_READER"]})
    data["evses"][1].update({"capabilities": ["RFID_READER"]})

    return data


@pytest.fixture
def location_example_with_evse_evse_id_none(location_example):
    location_example.update(
        {
            "evses": [
                {
                    "uid": "EVSE-1",
                    "status": "AVAILABLE",
                    "connectors": [
                        {
                            "id": "1",
                            "standard": "IEC_62196_T2",
                            "power_type": "AC_3_PHASE",
                            "format": "SOCKET",
                            "max_voltage": 10000,
                            "max_amperage": 50,
                            "last_updated": "2024-07-16T08:20:20Z",
                        }
                    ],
                }
            ]
        }
    )

    return location_example
