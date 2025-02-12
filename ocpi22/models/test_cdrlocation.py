import pytest

from ocpi22.conftest import create_ocpi_session_with_tariff
from ocpi22.models.cdrlocation import CdrLocation


@pytest.mark.django_db
def test_cdrlocation_string_conversion_to_show_correct_data(default_cdrlocation):
    assert (
        str(default_cdrlocation)
        == '"Location A" at Alfred Nobellaan 22 App 150Z, Harelbeke, BEL'
    )


@pytest.mark.django_db
def test_cdrlocation_creation_based_on_session_to_succeed():
    default_ocpi_session = create_ocpi_session_with_tariff()
    cdrlocation = CdrLocation.get_or_create_from_session(default_ocpi_session)
    assert cdrlocation.uid == default_ocpi_session.location.uid
    assert cdrlocation.evse_uid == default_ocpi_session.evse.uid
    assert cdrlocation.connector_id == default_ocpi_session.connector.uid

    def check_coordinate(coordinate: str):
        integer, decimals = coordinate.split(".")
        assert integer.isdigit()
        assert decimals.isdigit()
        assert len(decimals) == 6

    check_coordinate(cdrlocation.latitude)
    check_coordinate(cdrlocation.longitude)
