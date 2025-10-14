import os

import orjson
import pytest
from paho.mqtt.client import MQTTMessage

from ocpi22.tests.factories import LocationFactory, EvseFactory, CredentialsRoleFactory


@pytest.fixture
def smappee_status_topic():
    return os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")


@pytest.fixture
def smappee_meter_topic():
    return os.getenv("SMAPPEE_METER_VALUES_TOPIC")


@pytest.fixture
def smappee_auth_request_topic(monkeypatch):
    monkeypatch.setenv("SMAPPEE_AUTH_REQUEST_TOPIC", "smappee/auth/request")


@pytest.fixture
def mqtt_topics_setup(monkeypatch):
    monkeypatch.setenv("SMAPPEE_METER_VALUES_TOPIC", "meter/values")
    monkeypatch.setenv("SMAPPEE_STATUS_UPDATE_TOPIC", "status/updates")
    monkeypatch.setenv("SMAPPEE_AUTH_REQUEST_TOPIC", "auth/requests")


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
            "timestamp": "2022-02-22T22:22:22+00:00",
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
            "kwh": 125.0,
            "power": 22.0,
            "timestamp": "2024-12-23T15:38:51.940979+00:00",
        }
    )
    message.qos = 1
    message.retain = False
    return message


@pytest.fixture
def auth_request_topic():
    return os.getenv("SMAPPEE_AUTH_REQUEST_TOPIC", "auth/request/topic")


@pytest.fixture
def auth_request_message(auth_request_topic):
    message = MQTTMessage()
    message.topic = auth_request_topic.encode("utf-8")
    message.payload = orjson.dumps(
        {
            "token_id": "TEST_TOKEN_123",
            "evse_id": "TEST_EVSE_456",
            "correlation_id": "CORR_ID_789",
        }
    )
    message.qos = 1
    message.retain = False
    return message


@pytest.fixture
def mqtt_message():
    def _create_message(topic, payload=None):
        message = MQTTMessage()
        message.topic = topic.encode("utf-8") if isinstance(topic, str) else topic
        if payload:
            message.payload = (
                payload.encode("utf-8") if isinstance(payload, str) else payload
            )
        else:
            message.payload = b'{"test": "data"}'
        message.qos = 1
        message.retain = False
        return message

    return _create_message


@pytest.fixture
def hubject_credentialsrole():
    return CredentialsRoleFactory(
        country_code="DE",
        party_id="ICE",
        role="HUB",
    )
