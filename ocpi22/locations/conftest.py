import pytest

from ocpi22.tests.factories import LocationFactory


@pytest.fixture
def exclusive_location():
    return LocationFactory(publish=False, uid="PRIVATE")


@pytest.fixture
def public_location():
    return LocationFactory(publish=True, uid="PUBLIC")
