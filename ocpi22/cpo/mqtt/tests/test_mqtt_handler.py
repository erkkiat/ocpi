from unittest.mock import patch
import pytest
from paho.mqtt.client import MQTTMessage

from ocpi22.cpo.mqtt.mqtt_handler import on_message
from ocpi22.tests.factories import OCPISessionFactory
from orjson import orjson
from datetime import datetime
import pytz


@pytest.fixture
def enable_mqtt_authorize(monkeypatch):
    monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", True)


class TestOnMessageAuthRequest:
    @pytest.mark.django_db
    def test_on_message_calls_process_authorize_data_when_auth_topic_matches(
        self, enable_mqtt_authorize, auth_request_message, caplog
    ):
        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            on_message(None, None, auth_request_message)
            mock_process_authorize.assert_called_once_with(auth_request_message)
            assert "Received authorize message" in caplog.text

    def test_on_message_handles_auth_topic_with_partial_match(
        self, smappee_auth_request_topic, caplog, monkeypatch
    ):
        monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", "True")

        message = MQTTMessage()
        message.topic = "smappee/site/123/auth/request/456".encode("utf-8")
        message.payload = b'{"token_id": "test_token"}'

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", "smappee/auth/request"
        ):
            with patch(
                "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
            ) as mock_process_authorize:
                on_message(None, None, message)

                mock_process_authorize.assert_called_once_with(message)
                assert "Received authorize message" in caplog.text

    def test_on_message_does_not_call_authorize_when_auth_topic_not_matched(
        self, mqtt_topics_setup
    ):
        message = MQTTMessage()
        message.topic = "completely/different/topic".encode("utf-8")
        message.payload = b'{"token_id": "test_token"}'

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            on_message(None, None, message)
            mock_process_authorize.assert_not_called()

    def test_on_message_authorize_handles_process_authorize_data_exception(
        self, enable_mqtt_authorize, auth_request_message, caplog
    ):
        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            mock_process_authorize.side_effect = Exception("Processing failed")

            result = on_message(None, None, auth_request_message)

            mock_process_authorize.assert_called_once_with(auth_request_message)

            assert "Received authorize message" in caplog.text
            assert "MQTT message processing failed on topic" in caplog.text
            assert "subscriber continues running" in caplog.text
            assert "Processing failed" in caplog.text

            assert result is None

    @pytest.mark.parametrize(
        "mqtt_authorize,env_name",
        [
            ("True", "development"),
            ("true", "test"),
            ("1", "staging"),
        ],
    )
    def test_on_message_processes_authorize_when_mqtt_authorize_enabled(
        self, auth_request_message, caplog, monkeypatch, mqtt_authorize, env_name
    ):
        monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", mqtt_authorize)
        monkeypatch.setenv("ENV", env_name)

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            result = on_message(None, None, auth_request_message)

            mock_process_authorize.assert_called_once_with(auth_request_message)
            assert "Received authorize message" in caplog.text
            assert result is None

    @pytest.mark.parametrize(
        "mqtt_authorize,env_name",
        [
            ("False", "production"),
            ("false", "development"),
            ("0", "test"),
        ],
    )
    def test_on_message_returns_early_when_mqtt_authorize_disabled(
        self, auth_request_message, caplog, monkeypatch, mqtt_authorize, env_name
    ):
        monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", mqtt_authorize)
        monkeypatch.setenv("ENV", env_name)

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            result = on_message(None, None, auth_request_message)

            mock_process_authorize.assert_not_called()
            assert (
                f"Authorizing over mqtt is not enabled for {env_name}, please use http authorize instead"
                in caplog.text
            )
            assert result is None

    def test_on_message_mqtt_authorize_missing_env_var_defaults_to_disabled(
        self, auth_request_message, caplog, monkeypatch
    ):
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("ENABLE_MQTT_AUTHORIZE", raising=False)

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
        ) as mock_process_authorize:
            result = on_message(None, None, auth_request_message)

            mock_process_authorize.assert_not_called()
            assert (
                "Authorizing over mqtt is not enabled for production, please use http authorize instead"
                in caplog.text
            )
            assert result is None


class TestOnMessageUnknownTopicEdgeCases:
    def test_on_message_returns_none_for_empty_topic(
        self, mqtt_topics_setup, mqtt_message, caplog
    ):
        message = mqtt_message("")
        result = on_message(None, None, message)

        assert result is None
        assert "Unknown topic " in caplog.text

    def test_on_message_handles_topic_with_special_characters(
        self, mqtt_topics_setup, mqtt_message, caplog
    ):
        message = mqtt_message("topic/with/special/chars/@#$%")
        result = on_message(None, None, message)

        assert result is None
        assert "Unknown topic topic/with/special/chars/@#$%" in caplog.text

    def test_on_message_does_not_call_any_process_function_for_unknown_topic(
        self, mqtt_topics_setup, mqtt_message
    ):
        message = mqtt_message("completely/unknown/topic")

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.process_meter_values_data"
        ) as mock_meter:
            with patch(
                "ocpi22.cpo.mqtt.mqtt_handler.process_status_update_data"
            ) as mock_status:
                with patch(
                    "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
                ) as mock_auth:
                    on_message(None, None, message)

                    mock_meter.assert_not_called()
                    mock_status.assert_not_called()
                    mock_auth.assert_not_called()

    @pytest.mark.parametrize(
        "topic",
        [
            "completely/different",
            "another/unknown/topic",
            "random/topic/here",
            "test/something/else",
        ],
    )
    def test_on_message_unknown_topic_with_similar_but_not_matching_patterns(
        self, mqtt_topics_setup, mqtt_message, caplog, topic
    ):
        message = mqtt_message(topic)
        result = on_message(None, None, message)

        assert result is None
        assert f"Unknown topic {topic}" in caplog.text

    @pytest.mark.parametrize(
        "topic",
        [
            "meter_data",
            "status_info",
            "auth_token",
            "unknown_topic",
        ],
    )
    def test_on_message_returns_none_for_topics_without_keywords(
        self, monkeypatch, mqtt_topics_setup, mqtt_message, caplog, topic
    ):
        message = mqtt_message(topic)
        result = on_message(None, None, message)

        assert result is None
        assert f"Unknown topic {topic}" in caplog.text


class TestOnMessageTopicMatching:
    def test_on_message_topic_matching_uses_split_correctly(
        self, smappee_auth_request_topic, monkeypatch
    ):
        monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", "True")

        message_topic = "smappee/devices/site/123/auth/request/session/456"

        message = MQTTMessage()
        message.topic = message_topic.encode("utf-8")
        message.payload = b'{"token_id": "test"}'

        with patch(
            "ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", "smappee/auth/request"
        ):
            with patch(
                "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
            ) as mock_process_authorize:
                on_message(None, None, message)
                mock_process_authorize.assert_called_once_with(message)

    def test_on_message_topic_matching_case_sensitive(self, mqtt_topics_setup, caplog):
        message = MQTTMessage()
        message.topic = "smappee/auth/REQUEST".encode("utf-8")
        message.payload = b'{"token_id": "test"}'

        result = on_message(None, None, message)

        assert result is None
        assert "Unknown topic smappee/auth/REQUEST" in caplog.text

    def test_on_message_handles_topic_with_single_segment(self, monkeypatch, caplog):
        monkeypatch.setenv("SMAPPEE_AUTH_REQUEST_TOPIC", "request")
        monkeypatch.setenv("ENABLE_MQTT_AUTHORIZE", "True")

        message = MQTTMessage()
        message.topic = "request".encode("utf-8")
        message.payload = b'{"token_id": "test"}'

        with patch("ocpi22.cpo.mqtt.mqtt_handler.AUTH_REQUEST_TOPIC", "request"):
            with patch(
                "ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data"
            ) as mock_process_authorize:
                on_message(None, None, message)

                mock_process_authorize.assert_called_once_with(message)
                assert "Received authorize message" in caplog.text


class TestOnMessage:
    def test_on_message_unknown_topic(
        self, monkeypatch, mqtt_topics_setup, mqtt_message, caplog
    ):
        message = mqtt_message("unknown/completely/different")
        result = on_message(None, None, message)

        assert result is None
        assert "Unknown topic unknown/completely/different" in caplog.text

    @pytest.mark.django_db
    def test_on_message_calls_process_status_update_data(
        self,
        smappee_status_update_message,
        db,
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
