import os

import orjson
import pytest
from paho.mqtt.client import MQTTMessage

from ocpi22.tests.factories import LocationFactory, EvseFactory


@pytest.fixture
def smappee_status_topic():
    return os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")


@pytest.fixture
def smappee_meter_topic():
    return os.getenv("SMAPPEE_METER_VALUES_TOPIC")


@pytest.fixture
def location_hki(db):
    return LocationFactory()


@pytest.fixture
def evse(location_hki, db):
    return EvseFactory(
        location=location_hki,
        status="RESERVED",
        uid="d80b60c1-751e-43b5-868b-9a60a41c5456",
    )


@pytest.fixture
def smappee_status_update_message(evse, smappee_status_topic):
    message = MQTTMessage()
    message.topic = smappee_status_topic.encode("utf-8")
    message.payload = f'{{"evse_uid":"{evse.uid}", "status":"AVAILABLE"}}'.encode(
        "utf-8"
    )
    return message


@pytest.fixture
def smappee_meter_message(smappee_meter_topic):
    message = MQTTMessage()
    message.topic = smappee_meter_topic.encode("utf-8")
    message.payload = orjson.dumps(
        {
            "session_id": "94f5993d-232a-4916-a801-4e408c24c9cc",
            "kwh": 1.1,
            "soc": 1.1,
            "power": 2.2,
            "timestamp": "2022-02-22T22:22:22",
        }
    )
    message.qos = 1
    message.retain = False
    return message


@pytest.fixture
def smappee_meter_message_from_wouter(smappee_meter_topic):
    message = MQTTMessage()
    message.topic = smappee_meter_topic.encode("utf-8")
    message.payload = orjson.dumps(
        {
            "session_id": "BE*SMP*S*5F6AA9AEF106482C9F8BE8F258D",
            "kWh": 125.0,
            "power": 22.0,
            "timestamp": "2024-12-23T15:38:51.940979300Z",
        }
    )
    message.qos = 1
    message.retain = False
    return message
