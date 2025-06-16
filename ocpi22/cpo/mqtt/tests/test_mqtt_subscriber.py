import os
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
import paho.mqtt.client as mqtt
import pytz
from orjson import orjson
from paho.mqtt.client import CallbackAPIVersion

from ocpi22.cpo.mqtt.mqtt_handler import on_message, get_topic, _subscribe, on_connect
from ocpi22.cpo.mqtt.mqtt_client import (
    MQTTClientSingleton,
    get_broker_username_password,
    get_broker_and_port,
)
from ocpi22.tests.factories import OCPISessionFactory


@pytest.fixture
def mqtt_client():
    """Fixture providing a real MQTT client for testing"""
    client = mqtt.Client(
        client_id="test_client", callback_api_version=CallbackAPIVersion.VERSION2
    )
    yield client
    try:
        client.disconnect()
        client.loop_stop()
    except Exception:
        pass


@pytest.fixture
def mock_broker_config(monkeypatch):
    """Fixture for consistent broker configuration"""
    monkeypatch.setenv("MQTT_BROKER", "test.broker.com")
    monkeypatch.setenv("MQTT_PORT", "1883")
    monkeypatch.setenv("MQTT_USERNAME", "test_user")
    monkeypatch.setenv("MQTT_PASSWORD", "test_pass")
    monkeypatch.setenv("MQTT_USE_SSL", "False")


@pytest.fixture
def reset_singleton():
    yield
    MQTTClientSingleton._instance = None


class TestMqttSubscriber:
    _smappee_status_topic = os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")
    _smappee_meter_topic = os.getenv("SMAPPEE_METER_VALUES_TOPIC")

    @pytest.mark.django_db
    def test_on_message_calls_process_status_update_data(
        self, smappee_status_update_message, db, celery_app, celery_worker
    ):
        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_status_update_data"
        ) as mock_process_status_update_data:
            on_message(None, None, smappee_status_update_message)
            mock_process_status_update_data.assert_called_once_with(
                smappee_status_update_message
            )

    @pytest.mark.django_db
    def test_on_message_calls_process_meter_values(self, smappee_meter_message):
        session = OCPISessionFactory(
            uid=orjson.loads(smappee_meter_message.payload)["session_id"]
        )
        with patch(
            "ocpi22.cpo.mqtt.services.process_meter_values"
        ) as mock_process_meter_values:
            on_message(None, None, smappee_meter_message)
            mock_process_meter_values.assert_called_once_with(
                request=None,
                kwh=1.1,
                soc=1.1,
                power=2.2,
                timestamp=datetime(2022, 2, 22, 22, 22, 22, tzinfo=pytz.UTC),
                session=session,
            )

    def test_get_topic_from_env_var_success(self, monkeypatch):
        topic = "test_topic"
        monkeypatch.setenv("TEST_TOPIC", topic)
        assert get_topic("TEST_TOPIC") == topic

    def test_get_topic_from_env_var_raises_when_not_found(self):
        with pytest.raises(ValueError):
            get_topic("NOT_FOUND_TOPIC")

    def test_get_broker_username_password_success(self, monkeypatch):
        username = "test_username"
        password = "test_password"
        monkeypatch.setenv("MQTT_USERNAME", username)
        monkeypatch.setenv("MQTT_PASSWORD", password)
        assert get_broker_username_password() == (username, password)

    def test_get_broker_username_password_raise_when_any_not_found(self, monkeypatch):
        monkeypatch.delenv("MQTT_USERNAME", raising=False)
        monkeypatch.delenv("MQTT_PASSWORD", raising=False)
        with pytest.raises(ValueError):
            get_broker_username_password()

    def test_get_broker_and_port_success(self, monkeypatch):
        host = "mqtt://localhost"
        port = "1834"
        monkeypatch.setenv("MQTT_BROKER", host)
        monkeypatch.setenv("MQTT_PORT", port)
        assert get_broker_and_port() == (host, int(port))

    def test_get_broker_and_port_raises_when_not_found(self, monkeypatch):
        monkeypatch.delenv("MQTT_BROKER", raising=False)
        monkeypatch.delenv("MQTT_PORT", raising=False)
        with pytest.raises(ValueError):
            get_broker_and_port()

    def test_subscribe_success(self, mqtt_client, caplog):
        with patch.object(mqtt_client, "subscribe") as mock_subscribe:
            mock_subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)
            _subscribe(mqtt_client, "test/topic")

            mock_subscribe.assert_called_once_with("test/topic")
            assert "Successfully subscribed to test/topic" in caplog.text

    def test_subscribe_failure(self, mqtt_client, caplog):
        with patch.object(mqtt_client, "subscribe") as mock_subscribe:
            mock_subscribe.return_value = (mqtt.MQTT_ERR_NO_CONN, 1)
            _subscribe(mqtt_client, "test/topic")

            mock_subscribe.assert_called_once_with("test/topic")
            assert "Failed to subscribe to test/topic with error code 4" in caplog.text

    def test_subscribe_invalid_topic(self, mqtt_client, caplog):
        with patch.object(mqtt_client, "subscribe") as mock_subscribe:
            mock_subscribe.return_value = (mqtt.MQTT_ERR_INVAL, 1)
            _subscribe(mqtt_client, "invalid/topic")

            mock_subscribe.assert_called_once_with("invalid/topic")
            assert (
                "Failed to subscribe to invalid/topic with error code 3" in caplog.text
            )


@pytest.mark.usefixtures("reset_singleton")
class TestMQTTClientSingleton:
    def test_singleton_pattern(self):
        instance1 = MQTTClientSingleton()
        instance2 = MQTTClientSingleton()
        assert instance1 is instance2

    def test_singleton_initialization(self):
        instance = MQTTClientSingleton()
        assert instance._initialized is True
        assert instance.client is None

    def test_get_client_creates_client_when_none_exists(self):
        instance = MQTTClientSingleton()

        with patch.object(instance, "_create_and_connect_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            result = instance.get_client()

            mock_create.assert_called_once()
            assert result == mock_client
            assert instance.client == mock_client

    def test_get_client_returns_existing_client(self):
        instance = MQTTClientSingleton()
        mock_client = MagicMock()
        instance.client = mock_client

        with patch.object(instance, "_create_and_connect_client") as mock_create:
            result = instance.get_client()

            mock_create.assert_not_called()
            assert result == mock_client

    def test_configure_client_creates_proper_client(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client_id = "test_client_id"

        # Mock only the network connection, not the client creation
        with patch.object(instance, "_configure_ssl") as mock_ssl:
            mock_client = mqtt.Client(
                client_id=client_id, callback_api_version=CallbackAPIVersion.VERSION2
            )
            mock_ssl.return_value = mock_client

            result = instance._configure_client(client_id)

            assert result.on_connect == on_connect
            assert result.on_message == on_message
            assert result._client_id.decode() == client_id

    def test_configure_client_without_ssl_succeeds(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client_id = "test_client_id"

        result = instance._configure_client(client_id)

        assert result.on_connect == on_connect
        assert result.on_message == on_message
        assert result._client_id.decode() == client_id

    def test_connect_client_success(self, mock_broker_config):
        """Test successful client connection"""
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        # Mock only the actual connection to avoid network calls
        with patch.object(client, "connect") as mock_connect:
            instance._connect_client(client)
            mock_connect.assert_called_once_with("test.broker.com", 1883)

    def test_connect_client_with_retries_on_failure(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with patch.object(client, "connect") as mock_connect:
            with patch("time.sleep") as mock_sleep:
                mock_connect.side_effect = [
                    ConnectionError("Failed"),
                    None,
                ]  # Fail first, succeed second

                instance._connect_client(client, retries=2, delay=1)

                assert mock_connect.call_count == 2
                mock_sleep.assert_called_once_with(1)

    def test_connect_client_max_retries_exceeded_raises(self, mock_broker_config):
        """Test client connection failure after max retries"""
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with patch.object(client, "connect") as mock_connect:
            with patch("time.sleep"):
                mock_connect.side_effect = ConnectionError("Always fails")

                with pytest.raises(
                    ConnectionError,
                    match="Failed to connect to MQTT broker after retries",
                ):
                    instance._connect_client(client, retries=2, delay=1)

    def test_start_client_loops_forever(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        with patch.object(client, "loop_forever") as mock_loop_forever:
            instance.start_client(loop_forever=True)
            mock_loop_forever.assert_called_once()

    def test_start_client_loop_start(self):
        """Test start_client with loop_forever=False"""
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        # For loop_start, we don't need to mock as it's non-blocking
        instance.start_client(loop_forever=False)
        # Just verify no exception was raised

    def test_stop_client_succeeds(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        # These methods are safe to call on a real client
        instance.stop_client()
        assert instance.client is None

    def test_is_connected_returns_true_with_connected_client(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        with patch.object(client, "is_connected") as mock_is_connected:
            mock_is_connected.return_value = True
            assert instance.is_connected() is True

    def test_is_connected_returns_false_with_disconnected_client(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        # Real client will return False when not connected
        assert instance.is_connected() is False

    def test_is_connected_returns_false_when_no_client(self):
        instance = MQTTClientSingleton()
        assert instance.is_connected() is False

    def test_reset_client_succeeds(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        instance.reset_client()
        assert instance.client is None

    def test_configure_ssl(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        result = instance._configure_ssl(client)
        assert result is client


class TestOnConnect:
    def test_on_connect_success(self, caplog):
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with patch("ocpi22.cpo.mqtt.mqtt_handler._subscribe") as mock_subscribe:
            with patch("ocpi22.cpo.mqtt.mqtt_handler.METER_TOPIC", "meter/topic"):
                with patch("ocpi22.cpo.mqtt.mqtt_handler.STATUS_TOPIC", "status/topic"):
                    with patch(
                        "ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", "auth/topic"
                    ):
                        on_connect(client, None, None, 0)

                        assert "Connected successfully to the broker" in caplog.text
                        assert mock_subscribe.call_count == 3  # All three topics
                        mock_subscribe.assert_any_call(client, "meter/topic")
                        mock_subscribe.assert_any_call(client, "status/topic")
                        mock_subscribe.assert_any_call(client, "auth/topic")

    def test_on_connect_failure(self, caplog):
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        on_connect(client, None, None, 1)  # rc != 0 means failure

        assert "Failed to connect, return code 1" in caplog.text


class TestOnMessage:
    def test_on_message_unknown_topic(self, caplog):
        class MockMessage:
            def __init__(self, topic):
                self.topic = topic

        mock_message = MockMessage("unknown/completely/different")

        with patch("ocpi22.cpo.mqtt.mqtt_handler.METER_TOPIC", "meter/values"):
            with patch("ocpi22.cpo.mqtt.mqtt_handler.STATUS_TOPIC", "status/updates"):
                with patch(
                    "ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", "auth/requests"
                ):
                    result = on_message(None, None, mock_message)

                    assert result is None
                    assert "Unknown topic unknown/completely/different" in caplog.text
