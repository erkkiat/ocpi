import os
from unittest.mock import MagicMock

import pytest

from ocpi22.tests.factories import LocationFactory, EvseFactory


@pytest.fixture
def smappee_status_topic():
    return os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")


@pytest.fixture
def smappee_meter_topic():
    return os.getenv("SMAPPEE_METER_VALUES_TOPIC")


@pytest.fixture
def location_hki(self, db):
    return LocationFactory()


@pytest.fixture()
def evse(self, location_hki, db):
    return EvseFactory(location=location_hki, status="RESERVED")


@pytest.fixture
def smappee_status_update_message(evse, smappee_status_topic):
    message = MagicMock()
    message.topic = smappee_status_topic
    message.payload = f'{{"evse_uid":"{evse.uid}", "status":"AVAILABLE"}}'.encode(
        "utf-8"
    )
    return message


@pytest.fixture
def smappee_meter_message(smappee_meter_topic):
    message = MagicMock()
    message.topic = smappee_meter_topic
    message.payload = b'{"session_id": "94f5993d-232a-4916-a801-4e408c24c9cc", "internal_reference": "internal": "kw": 1.1, "soc": 1.1, "power": 2.2, timestamp": "2022-02-22T22:22:22"}'
