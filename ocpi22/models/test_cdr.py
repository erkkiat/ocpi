import pytest

from ocpi22.models.cdr import Cdr


@pytest.mark.django_db
def test_formatting_session_url_from_cdr(default_ocpi_session):
    cdr = Cdr.create_based_on_session(default_ocpi_session)
    assert cdr.session_id == default_ocpi_session.uid
    assert cdr.ocpi_master == default_ocpi_session.ocpi_master
