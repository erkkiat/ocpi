from unittest.mock import patch, MagicMock

import pytest
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

from ocpi22.cpo.mqtt.mqtt_handler import get_topic, _subscribe, on_connect
from ocpi22.cpo.mqtt.mqtt_client import (
    MQTTClientSingleton,
    get_broker_username_password,
    get_broker_and_port,
)


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


class TestGetTopic:
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
            _subscribe(mqtt_client, "test/topic", 0)

            mock_subscribe.assert_called_once_with("test/topic", 0)
            assert "Successfully subscribed to test/topic" in caplog.text

    def test_subscribe_failure(self, mqtt_client, caplog):
        with patch.object(mqtt_client, "subscribe") as mock_subscribe:
            mock_subscribe.return_value = (mqtt.MQTT_ERR_NO_CONN, 1)
            _subscribe(mqtt_client, "test/topic", 1)

            mock_subscribe.assert_called_once_with("test/topic", 1)
            assert "Failed to subscribe to test/topic with error code 4" in caplog.text

    def test_subscribe_invalid_topic(self, mqtt_client, caplog):
        with patch.object(mqtt_client, "subscribe") as mock_subscribe:
            mock_subscribe.return_value = (mqtt.MQTT_ERR_INVAL, 1)
            _subscribe(mqtt_client, "invalid/topic", 0)

            mock_subscribe.assert_called_once_with("invalid/topic", 0)
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

    def test_configure_client_sets_callbacks_with_db_wrapper(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client_id = "test_client_id"

        result = instance._configure_client(client_id)

        assert result.on_connect is not None
        assert result.on_message is not None
        assert result._client_id.decode() == client_id
        assert callable(result.on_connect)
        assert callable(result.on_message)

    def test_configure_client_sets_username_and_password(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client_id = "test_client_id"

        with patch.object(mqtt.Client, "username_pw_set") as mock_username_pw_set:
            instance._configure_client(client_id)

            mock_username_pw_set.assert_called_once_with("test_user", "test_pass")

    def test_connect_client_calls_connect_with_keepalive(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with patch.object(client, "connect") as mock_connect:
            instance._connect_client(client)
            mock_connect.assert_called_once_with("test.broker.com", 1883, keepalive=60)

    def test_connect_client_with_retries_on_failure(self, mock_broker_config):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with patch.object(client, "connect") as mock_connect:
            with patch("time.sleep") as mock_sleep:
                mock_connect.side_effect = [
                    ConnectionError("Failed"),
                    None,
                ]

                instance._connect_client(client, retries=2, delay=1)

                assert mock_connect.call_count == 2
                mock_sleep.assert_called_once_with(1)

    def test_connect_client_max_retries_exceeded_raises(self, mock_broker_config):
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
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        instance.start_client(loop_forever=False)

    def test_reset_client_succeeds(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        instance.client = client

        with patch("ocpi22.cpo.mqtt.mqtt_client.close_old_connections"):
            instance.reset_client()
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

        assert instance.is_connected() is False

    def test_is_connected_returns_false_when_no_client(self):
        instance = MQTTClientSingleton()
        assert instance.is_connected() is False

    def test_configure_ssl(self):
        instance = MQTTClientSingleton()
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        result = instance._configure_ssl(client)
        assert result is client


class TestOnConnect:
    def test_on_connect_success(self, monkeypatch, caplog):
        meter_topic = "meter/topic"
        status_topic = "status/topic"
        auth_topic = "auth/topic"

        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        with (
            patch("ocpi22.cpo.mqtt.mqtt_handler.METER_TOPIC", meter_topic),
            patch("ocpi22.cpo.mqtt.mqtt_handler.STATUS_TOPIC", status_topic),
            patch("ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", auth_topic),
            patch("ocpi22.cpo.mqtt.mqtt_handler._subscribe") as mock_subscribe,
        ):
            on_connect(client, None, None, 0)

            assert "Connected successfully to the broker" in caplog.text
            assert mock_subscribe.call_count == 3
            mock_subscribe.assert_any_call(client, meter_topic)
            mock_subscribe.assert_any_call(client, status_topic)
            mock_subscribe.assert_any_call(client, auth_topic, qos=1)

    def test_on_connect_failure(self, caplog):
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)

        on_connect(client, None, None, 1)

        assert "Failed to connect, return code 1" in caplog.text
