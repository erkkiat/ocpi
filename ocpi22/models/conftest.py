import pytest

from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.cdrtoken import CdrToken
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    OCPISessionFactory,
    CdrTokenFactory,
    CdrLocationFactory,
)


@pytest.fixture
def default_ocpi_session(cdr_receiver_credentials) -> Session:
    return OCPISessionFactory()


@pytest.fixture
def default_cdrtoken() -> CdrToken:
    return CdrTokenFactory()


@pytest.fixture
def default_cdrlocation() -> CdrLocation:
    return CdrLocationFactory()
