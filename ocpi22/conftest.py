import pytest

from ocpi22.models.cdr import Cdr
from ocpi22.models.session import Session
from ocpi22.tests.factories import OCPISessionFactory, TariffFactory


def create_ocpi_session(cdr_receiver_credentials) -> Session:
    session: Session = OCPISessionFactory()
    tariff = TariffFactory(uid="D9931A36-49A3-4C22-BA87-0E3C1792887B")
    session.connector.tariff_ids.set([tariff])
    return session


@pytest.fixture
def default_ocpi_session(cdr_receiver_credentials) -> Session:
    return create_ocpi_session(cdr_receiver_credentials)


@pytest.fixture
def default_ocpi_session_and_cdr(cdr_receiver_credentials) -> (Cdr, Session):
    session = create_ocpi_session(cdr_receiver_credentials)
    session.status = Session.COMPLETED
    session.save()
    return session, Cdr.objects.get(session_id=session.uid)
