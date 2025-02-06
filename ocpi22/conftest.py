import pytest

from ocpi22.models.cdr import Cdr
from ocpi22.models.session import Session
from ocpi22.tests.factories import OCPISessionFactory, TariffFactory


def create_ocpi_session_with_tariff() -> Session:
    session: Session = OCPISessionFactory()
    tariff = TariffFactory(uid="D9931A36-49A3-4C22-BA87-0E3C1792887B")
    session.connector.tariff_ids.set([tariff])
    return session


@pytest.fixture
def completed_session(cdr_receiver_credentials) -> Session:
    session = create_ocpi_session_with_tariff()
    session.status = Session.COMPLETED
    session.save()
    return session
