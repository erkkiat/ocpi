import os
from unittest.mock import patch

import pytest

from ocpi22.cpo.mqtt.mqtt_subscriber import (
    stop_and_disconnect,
    connect_client,
    on_message,
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
