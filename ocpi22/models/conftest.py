import pytest

from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.cdrtoken import CdrToken
from ocpi22.tests.factories import (
    CdrTokenFactory,
    CdrLocationFactory,
)


@pytest.fixture
def default_cdrtoken() -> CdrToken:
    return CdrTokenFactory()


@pytest.fixture
def default_cdrlocation() -> CdrLocation:
    return CdrLocationFactory()
