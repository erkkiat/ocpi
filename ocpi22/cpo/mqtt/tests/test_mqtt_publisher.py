import os
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from ocpi22.choices import AuthorizationEnum
from ocpi22.cpo.mqtt.mqtt_publisher import _get_auth_topic_name, publish_auth_response
from ocpi22.cpo.mqtt.schemas import TokenAuthorizationResponse


class TestGetAuthTopicName:
    def test_get_auth_topic_name_returns_default_when_env_var_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _get_auth_topic_name("NONEXISTENT_VAR")
            assert result == "servicelocation/roaming/authresponse"

    def test_get_auth_topic_name_returns_env_var_value_when_set(self):
        with patch.dict(os.environ, {"TEST_AUTH_TOPIC": "custom/auth/topic"}):
            result = _get_auth_topic_name("TEST_AUTH_TOPIC")
            assert result == "custom/auth/topic"

    def test_get_auth_topic_name_strips_share_prefix_when_present(self):
        with patch.dict(
            os.environ, {"SHARED_TOPIC": "$share/group1/actual/topic/path"}
        ):
            result = _get_auth_topic_name("SHARED_TOPIC")
            assert result == "actual/topic/path"

    def test_get_auth_topic_name_handles_share_prefix_with_minimal_path(self):
        with patch.dict(os.environ, {"MINIMAL_SHARED": "$share/group/minimal"}):
            result = _get_auth_topic_name("MINIMAL_SHARED")
            assert result == "minimal"

    def test_get_auth_topic_name_returns_topic_as_is_when_no_share_prefix(self):
        with patch.dict(os.environ, {"NORMAL_TOPIC": "normal/topic/without/share"}):
            result = _get_auth_topic_name("NORMAL_TOPIC")
            assert result == "normal/topic/without/share"


class TestPublishAuthResponse:
    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_successfully_publishes_message(
        self, mock_mqtt_singleton
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 0
        mock_client.publish.return_value = mock_publish_info

        with patch.dict(os.environ, {"SMAPPEE_AUTH_RESPONSE_TOPIC": "test/auth/topic"}):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.ALLOWED,
                session_id="session-123",
                correlation_id="corr-456",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once_with(
                "test/auth/topic",
                '{"allowed":"ALLOWED","session_id":"session-123","correlation_id":"corr-456"}',
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_uses_default_topic_when_env_var_not_set(
        self, mock_mqtt_singleton
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 0
        mock_client.publish.return_value = mock_publish_info

        with patch.dict(os.environ, {}, clear=True):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.ALLOWED,
                session_id="session-123",
                correlation_id="corr-456",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once_with(
                "servicelocation/roaming/authresponse",
                '{"allowed":"ALLOWED","session_id":"session-123","correlation_id":"corr-456"}',
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_handles_payload_with_none_session_id(
        self, mock_mqtt_singleton
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 0
        mock_client.publish.return_value = mock_publish_info

        with patch.dict(os.environ, {"SMAPPEE_AUTH_RESPONSE_TOPIC": "test/auth/topic"}):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.NOT_ALLOWED,
                session_id=None,
                correlation_id="corr-789",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once_with(
                "test/auth/topic",
                '{"allowed":"NOT_ALLOWED","correlation_id":"corr-789"}',
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_handles_shared_topic_prefix(
        self, mock_mqtt_singleton
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 0
        mock_client.publish.return_value = mock_publish_info

        with patch.dict(
            os.environ,
            {"SMAPPEE_AUTH_RESPONSE_TOPIC": "$share/group1/actual/auth/topic"},
        ):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.ALLOWED,
                session_id="session-456",
                correlation_id="corr-123",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once_with(
                "actual/auth/topic",
                '{"allowed":"ALLOWED","session_id":"session-456","correlation_id":"corr-123"}',
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_returns_early_when_serialization_fails(
        self, mock_mqtt_singleton, caplog
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        payload = MagicMock(spec=TokenAuthorizationResponse)
        payload.model_dump_json.side_effect = ValidationError.from_exception_data(
            "TokenAuthorizationResponse",
            [{"type": "missing", "loc": ("test",), "msg": "Test error"}],
        )

        publish_auth_response(payload)

        mock_client.publish.assert_not_called()
        assert any(
            "Failed serializing MQTT auth payload" in record.message
            for record in caplog.records
        )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_logs_error_when_publish_returns_non_zero_rc(
        self, mock_mqtt_singleton, caplog
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 5
        mock_client.publish.return_value = mock_publish_info

        with patch.dict(os.environ, {"SMAPPEE_AUTH_RESPONSE_TOPIC": "test/auth/topic"}):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.ALLOWED,
                session_id="session-123",
                correlation_id="corr-456",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once()
            assert any(
                "MQTT publish failed with result code 5" in record.message
                for record in caplog.records
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_logs_exception_when_publish_raises_exception(
        self, mock_mqtt_singleton, caplog
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_client.publish.side_effect = Exception("Connection failed")

        with patch.dict(os.environ, {"SMAPPEE_AUTH_RESPONSE_TOPIC": "test/auth/topic"}):
            payload = TokenAuthorizationResponse(
                allowed=AuthorizationEnum.BLOCKED,
                session_id="session-789",
                correlation_id="corr-123",
            )

            publish_auth_response(payload)

            mock_client.publish.assert_called_once()
            assert any(
                "Failed to publish auth response to MQTT" in record.message
                for record in caplog.records
            )

    @patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")
    def test_publish_auth_response_excludes_unset_fields_in_json_serialization(
        self, mock_mqtt_singleton
    ):
        mock_client = MagicMock()
        mock_mqtt_singleton.return_value.get_client.return_value = mock_client

        mock_publish_info = MagicMock()
        mock_publish_info.rc = 0
        mock_client.publish.return_value = mock_publish_info

        payload = MagicMock(spec=TokenAuthorizationResponse)
        payload.model_dump_json.return_value = (
            '{"allowed":"ALLOWED","correlation_id":"test"}'
        )

        publish_auth_response(payload)

        payload.model_dump_json.assert_called_once_with(exclude_none=True)
