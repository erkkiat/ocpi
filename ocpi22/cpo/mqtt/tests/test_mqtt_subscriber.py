import os
from unittest.mock import patch, MagicMock

import pytest
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from ocpi22.cpo.mqtt import mqtt_subscriber
from ocpi22.cpo.mqtt.mqtt_subscriber import (
    stop_and_disconnect,
    connect_client,
    on_message,
    get_topic,
    get_broker_username_password,
    get_broker_and_port,
    configure_client,
    on_connect,
    start_client,
)


class TestMqttSubscriber:
    _smappee_status_topic = os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC")
    _smappee_meter_topic = os.getenv("SMAPPEE_METER_VALUES_TOPIC")

    @pytest.fixture
    def mocked_mqtt_client(self):
        with patch("paho.mqtt.client.Client", autospec=True) as MockClient:
            mock_mqtt_client = MockClient.return_value
            client = connect_client()
            client.on_connect(mock_mqtt_client, None, None, 0)
            yield mock_mqtt_client

    @pytest.mark.parametrize("topic", [_smappee_status_topic, _smappee_meter_topic])
    def test_subscribe(self, mocked_mqtt_client, topic):
        mocked_mqtt_client.subscribe.assert_any_call(topic)
        stop_and_disconnect(mocked_mqtt_client)

    @pytest.mark.asyncio
    def test_on_message_calls_process_status_update_data(
        self, smappee_status_update_message
    ):
        with patch(
            "ocpi22.cpo.mqtt.mqtt_subscriber.process_status_update_data"
        ) as mock_process_status_update:
            on_message(None, None, smappee_status_update_message)
            mock_process_status_update.assert_called_once_with(
                smappee_status_update_message
            )

    def test_on_message_calls_process_meter_values(self, smappee_meter_message):
        with patch(
            "ocpi22.cpo.mqtt.mqtt_subscriber.process_meter_values_data"
        ) as mock_process_meter_values:
            on_message(None, None, smappee_meter_message)
            mock_process_meter_values.assert_called_once_with(smappee_meter_message)

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
        host = "localhost"
        port = "1834"
        monkeypatch.setenv("MQTT_HOST", host)
        monkeypatch.setenv("MQTT_PORT", port)
        assert get_broker_and_port() == (host, int(port))

    def test_get_broker_and_port_raises_when_not_found(self, monkeypatch):
        monkeypatch.delenv("MQTT_HOST", raising=False)
        monkeypatch.delenv("MQTT_PORT", raising=False)
        with pytest.raises(ValueError):
            get_broker_and_port()

    def test_configure_client(self):
        mock_client_id = "test_client_id"
        mock_username = "test_username"
        mock_password = "test_password"
        mock_client_instance = MagicMock()

        with patch.object(
            mqtt_subscriber,
            "get_broker_username_password",
            return_value=(mock_username, mock_password),
        ):
            with patch.object(
                mqtt, "Client", return_value=mock_client_instance
            ) as mock_mqtt_client:
                client = configure_client(mock_client_id)
                mock_mqtt_client.assert_called_once_with(
                    client_id=mock_client_id,
                    callback_api_version=CallbackAPIVersion.VERSION2,
                )
                mock_client_instance.username_pw_set.assert_called_once_with(
                    mock_username, mock_password
                )
                assert client.on_connect == on_connect
                assert client.on_message == on_message

    def test_start_client_with_loop_start_when_it_set_to_false(self, monkeypatch):
        mock_client = MagicMock(spec=mqtt.Client)
        monkeypatch.setenv("MQTT_LOOP_FOREVER", "False")
        start_client(mock_client)
        mock_client.loop_start.assert_called_once()
        mock_client.loop_forever.assert_not_called()

    def test_start_client_with_loop_forever_when_it_set_to_true(self, monkeypatch):
        mock_client = MagicMock(spec=mqtt.Client)
        monkeypatch.setenv("MQTT_LOOP_FOREVER", "True")
        start_client(mock_client)
        mock_client.loop_forever.assert_called_once()
        mock_client.loop_start.assert_not_called()

    def test_stop_and_disconnect(self):
        mock_client = MagicMock(spec=mqtt.Client)
        stop_and_disconnect(mock_client)
        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()

    def test_connect_client(self):
        mock_client = MagicMock(spec=mqtt.Client)
        with patch.object(
            mqtt_subscriber, "configure_client", return_value=mock_client
        ) as mock_configure_client:
            with patch.object(
                mqtt_subscriber, "get_broker_and_port", return_value=("localhost", 1834)
            ) as mock_get_broker_and_port:
                client = connect_client()
                mock_configure_client.assert_called_once()
                mock_get_broker_and_port.assert_called_once()
                mock_client.connect.assert_called_once_with("localhost", 1834)
                assert client == mock_client
