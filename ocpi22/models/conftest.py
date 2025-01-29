import pytest

from ocpi22.models.session import Session
from ocpi22.tests.factories import OCPISessionFactory


@pytest.fixture
def default_ocpi_session(cdr_receiver_credentials) -> Session:
    return OCPISessionFactory()
