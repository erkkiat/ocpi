import pytest

from ocpi22.models.session import Session
from ocpi22.tests.factories import OCPISessionFactory, TariffFactory


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
