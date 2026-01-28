import logging
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch, Mock

import orjson
import pytest
import pytz
from kombu.exceptions import OperationalError

from ocpi22.choices import AuthorizationEnum
from ocpi22.cpo.api import process_meter_values, is_meter_value_frequency_within_limit
from ocpi22.cpo.mqtt.schemas import (
    EvseStatusUpdate,
    TokenAuthorizationMessageIn,
    TokenAuthorizationResponse,
    CachedSession,
)
from ocpi22.cpo.mqtt.services import (
    _decode_message,
    process_meter_values_data,
    process_status_update_data,
    _find_token_by_uid,
    process_authorize_data,
    _authorize_and_publish,
    create_and_save_session,
)
from ocpi22.cpo.mqtt.tasks import save_and_send_evse_status_updates
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.tests.factories import (
    OCPISessionFactory,
    ConnectorFactory,
    LocationFactory,
    EvseFactory,
    TariffFactory,
    TokenFactory,
    CredentialsRoleFactory,
    CredentialsFactory,
)
from ocpi22.tokens.auth import TokenAuthorization
from ocpi22.tokens.dataclasses import TokenReference


class TestDecodeMessage:
    def test_decode_message_returns_decoded_string_when_valid_utf8(
        self, smappee_status_update_message
    ):
        result = _decode_message(smappee_status_update_message)

        assert result == (
            '{"evse_uid":"D80B60C1-751E-43B5-868B-9A60A41C5456", "status":"AVAILABLE"}'
        )

    def test_decode_message_returns_none_when_unicode_decode_error(
        self, smappee_status_update_message, caplog
    ):
        smappee_status_update_message.payload = b"\x80"

        result = _decode_message(smappee_status_update_message)

        assert result is None
        assert any(
            f"Failed to decode message from topic {smappee_status_update_message.topic}"
            in record.message
            for record in caplog.records
        )


@pytest.mark.django_db
class TestProcessMeterValuesData:
    def test_process_meter_values_data_exits_early_when_decode_message_fails(
        self, smappee_meter_message
    ):
        smappee_meter_message.payload = b"\x80"

        with (
            patch(
                "ocpi22.cpo.mqtt.services._decode_message", return_value=None
            ) as mock_decode_message,
            patch("ocpi22.cpo.mqtt.services.update_meter_values_async") as mock_task,
        ):
            result = process_meter_values_data(smappee_meter_message)

            assert result is None
            mock_decode_message.assert_called_once_with(smappee_meter_message)
            mock_task.apply_async.assert_not_called()

    def test_process_meter_values_data_exits_early_when_data_validation_fails(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.ERROR, logger="ocpi22.cpo.mqtt.services")
        smappee_meter_message.payload = b'{"invalid_data": "94f5993d-232a-4916-a801-4e408c24c9cc", "kw": 1.1, "soc": 1.1, "power": 2.2, timestamp": "2022-02-22T22:22:22"}'

        result = process_meter_values_data(smappee_meter_message)

        assert result is None
        assert any(
            f"Failed to parse message from topic { smappee_meter_message.topic}"
            in record.message
            for record in caplog.records
        )

    def test_process_meter_values_data_exits_early_when_session_id_missing(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.WARNING, logger="ocpi22.cpo.mqtt.services")
        smappee_meter_message.payload = orjson.dumps(
            {
                "session_id": None,
                "kwh": 1.1,
                "soc": 1.1,
                "power": 2.2,
                "timestamp": "2022-02-22T22:22:22+00:00",
            }
        )

        with patch("ocpi22.cpo.mqtt.services.update_meter_values_async") as mock_task:
            result = process_meter_values_data(smappee_meter_message)

            assert result is None
            mock_task.apply_async.assert_not_called()
            assert any(
                "Meter values message missing session_id" in record.message
                for record in caplog.records
            )

    @pytest.mark.django_db
    def test_process_meter_values_data_dispatches_task_with_correct_parameters(
        self, smappee_meter_message
    ):
        with patch("ocpi22.cpo.mqtt.services.update_meter_values_async") as mock_task:
            process_meter_values_data(smappee_meter_message)

            mock_task.apply_async.assert_called_once_with(
                kwargs={
                    "session_id": "94f5993d-232a-4916-a801-4e408c24c9cc",
                    "timestamp": "2022-02-22T22:22:22+00:00",
                    "kwh": 1.1,
                    "soc": 1.1,
                    "power": 2.2,
                },
                expires=60,
            )

    def test_process_meter_values_data_logs_error_when_celery_operational_error_occurs(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.ERROR, logger="ocpi22.cpo.mqtt.services")

        with patch(
            "ocpi22.cpo.mqtt.services.update_meter_values_async.apply_async",
            side_effect=OperationalError("Celery broker unavailable"),
        ):
            result = process_meter_values_data(smappee_meter_message)

            assert result is None
            assert any(
                "Celery operational error while dispatching meter values task"
                in record.message
                for record in caplog.records
            )

    def test_process_meter_values_data_logs_error_when_unexpected_error_occurs(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.ERROR, logger="ocpi22.cpo.mqtt.services")

        with patch(
            "ocpi22.cpo.mqtt.services.update_meter_values_async.apply_async",
            side_effect=Exception("Unexpected error"),
        ):
            result = process_meter_values_data(smappee_meter_message)

            assert result is None
            assert any(
                "Unexpected error dispatching meter values task" in record.message
                for record in caplog.records
            )

    def test_process_meter_values_data_dispatches_task_with_none_for_optional_fields(
        self, smappee_meter_topic
    ):
        from paho.mqtt.client import MQTTMessage

        OCPISessionFactory(uid="test-session-123")
        message = MQTTMessage()
        message.topic = smappee_meter_topic.encode("utf-8")
        message.payload = orjson.dumps(
            {
                "session_id": "test-session-123",
                "kwh": 5.5,
                "soc": None,
                "power": None,
                "timestamp": "2023-03-15T10:30:00+00:00",
            }
        )

        with patch("ocpi22.cpo.mqtt.services.update_meter_values_async") as mock_task:
            process_meter_values_data(message)

            mock_task.apply_async.assert_called_once_with(
                kwargs={
                    "session_id": "test-session-123",
                    "timestamp": "2023-03-15T10:30:00+00:00",
                    "kwh": 5.5,
                    "soc": None,
                    "power": None,
                },
                expires=60,
            )

    def test_process_meter_values_data_logs_success_when_task_dispatched(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.INFO, logger="ocpi22.cpo.mqtt.services")

        with patch("ocpi22.cpo.mqtt.services.update_meter_values_async"):
            process_meter_values_data(smappee_meter_message)

            assert any(
                "Dispatched meter values update task for session 94f5993d-232a-4916-a801-4e408c24c9cc"
                in record.message
                for record in caplog.records
            )

    @pytest.mark.parametrize(
        "kwh,soc,power",
        [
            (10.5, 50.0, 22.0),
            (0.0, 0.0, 0.0),
            (100.5, 100.0, 50.0),
            (5.25, None, 11.0),
            (15.0, 80.0, None),
        ],
    )
    def test_process_meter_values_data_handles_various_meter_value_combinations(
        self, smappee_meter_topic, kwh, soc, power
    ):
        from paho.mqtt.client import MQTTMessage

        OCPISessionFactory(uid="test-session-456")
        message = MQTTMessage()
        message.topic = smappee_meter_topic.encode("utf-8")
        message.payload = orjson.dumps(
            {
                "session_id": "test-session-456",
                "kwh": kwh,
                "soc": soc,
                "power": power,
                "timestamp": "2023-03-15T10:30:00+00:00",
            }
        )

        with patch("ocpi22.cpo.mqtt.services.update_meter_values_async") as mock_task:
            process_meter_values_data(message)

            call_kwargs = mock_task.apply_async.call_args[1]["kwargs"]
            assert call_kwargs["kwh"] == kwh
            assert call_kwargs["soc"] == soc
            assert call_kwargs["power"] == power

    def test_process_meter_values_data_exits_early_when_meter_value_frequency_returns_false(
        self, smappee_meter_topic, caplog
    ):
        from paho.mqtt.client import MQTTMessage

        OCPISessionFactory(uid="test-session-456")
        message = MQTTMessage()
        message.topic = smappee_meter_topic.encode("utf-8")
        message.payload = orjson.dumps(
            {
                "session_id": "test-session-456",
                "kwh": 14,
                "soc": 29,
                "power": 17000,
                "timestamp": "2023-03-15T10:30:00+00:00",
            }
        )

        with (
            patch(
                "ocpi22.cpo.mqtt.services.is_meter_value_frequency_within_limit"
            ) as mock_check_meter_values_frequency,
            patch(
                "ocpi22.cpo.mqtt.services.update_meter_values_async.apply_async"
            ) as mock_task,
        ):
            mock_check_meter_values_frequency.return_value = False
            process_meter_values_data(message)

            mock_task.assert_not_called()
            assert (
                "Skipping meter values update for session test-session-456 due to high frequency"
                in caplog.text
            )

    def test_process_meter_values_data_does_not_exits_early_when_meter_value_frequency_returns_false(
        self, smappee_meter_topic, caplog
    ):
        from paho.mqtt.client import MQTTMessage

        OCPISessionFactory(uid="test-session-456")
        message = MQTTMessage()
        message.topic = smappee_meter_topic.encode("utf-8")
        message.payload = orjson.dumps(
            {
                "session_id": "test-session-456",
                "kwh": 14,
                "soc": 29,
                "power": 17000,
                "timestamp": "2023-03-15T10:30:00+00:00",
            }
        )

        with (
            patch(
                "ocpi22.cpo.mqtt.services.is_meter_value_frequency_within_limit"
            ) as mock_check_meter_values_frequency,
            patch(
                "ocpi22.cpo.mqtt.services.update_meter_values_async.apply_async"
            ) as mock_task,
        ):
            mock_check_meter_values_frequency.return_value = True
            process_meter_values_data(message)

            mock_task.assert_called_once()
            assert (
                "Dispatched meter values update task for session test-session-456"
                in caplog.text
            )


class TestProcessStatusUpdateData:
    def test_process_status_update_data_exits_early_when_decode_message_fails(
        self,
        smappee_status_update_message,
    ):
        smappee_status_update_message.payload = b"\x80"

        with (
            patch(
                "ocpi22.cpo.mqtt.services._decode_message", return_value=None
            ) as mock_decode_message,
            patch.object(
                EvseStatusUpdate, attribute="model_validate_json"
            ) as mock_validate,
            patch.object(
                save_and_send_evse_status_updates, attribute="apply_async"
            ) as mock_apply_async,
        ):
            result = process_status_update_data(smappee_status_update_message)

            assert result is None
            mock_decode_message.assert_called_once_with(smappee_status_update_message)
            mock_validate.assert_not_called()
            mock_apply_async.assert_not_called()

    def test_process_status_update_data_exits_early_when_data_validation_fails(
        self, smappee_status_update_message, caplog
    ):
        smappee_status_update_message.payload = b'{"invalid_data": "94f5993d-232a"}'

        result = process_status_update_data(smappee_status_update_message)

        assert result is None
        assert any(
            f"Failed to parse message from topic {smappee_status_update_message.topic}"
            in record.message
            for record in caplog.records
        )

    def test_process_status_update_data_logs_error_when_celery_operational_error_occurs(
        self, smappee_status_update_message, caplog
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        evse_status.model_dump.return_value = {
            "invalid_field": "invalid",
            "status": "AVAILABLE",
            "evse_uid": "d80b60c1-751e-43b5-868b-9a60a41c5456",
        }

        with (
            patch.object(
                EvseStatusUpdate, "model_validate_json", return_value=evse_status
            ),
            patch.object(
                save_and_send_evse_status_updates,
                "apply_async",
                side_effect=OperationalError("Some error from celery"),
            ),
        ):
            result = process_status_update_data(smappee_status_update_message)

            assert result is None
            assert any(
                "Celery operational error" in record.message
                for record in caplog.records
            )

    def test_process_status_update_data_logs_error_when_unexpected_error_occurs(
        self, smappee_status_update_message, caplog, db
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        evse_status.model_dump.return_value = {
            "evse_uid": "d80b60c1-751e-43b5-868b-9a60a41c5456",
            "status": "AVAILABLE",
            "invalid_field": "invalid",
        }

        with (
            patch.object(
                EvseStatusUpdate, "model_validate_json", return_value=evse_status
            ),
            patch.object(
                save_and_send_evse_status_updates,
                "apply_async",
                side_effect=Exception("Some unexpected error"),
            ),
        ):
            result = process_status_update_data(smappee_status_update_message)

            assert result is None
            assert any(
                "An unexpected error occurred" in record.message
                for record in caplog.records
            )

    def test_process_status_update_data_dispatches_celery_task_with_correct_parameters(
        self, smappee_status_update_message
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        decoded_message = _decode_message(smappee_status_update_message)
        message_dict = orjson.loads(decoded_message)
        evse_status.model_dump.return_value = message_dict

        with (
            patch.object(
                EvseStatusUpdate, "model_validate_json", return_value=evse_status
            ),
            patch.object(
                save_and_send_evse_status_updates, "apply_async"
            ) as mock_save_and_send_evse_status_updates_task,
        ):
            process_status_update_data(smappee_status_update_message)

            mock_save_and_send_evse_status_updates_task.assert_called_once_with(
                args=[message_dict["evse_uid"], message_dict["status"]], expires=35
            )


class TestProcessMeterValuesFrequency:
    @pytest.mark.django_db
    def test_process_meter_values_allows_update_when_meter_values_received_within_accepted_frequency(
        self,
    ):
        with (
            patch(
                "ocpi22.cpo.api.is_meter_value_frequency_within_limit"
            ) as mock_check_meter_values_frequency,
            patch(
                "ocpi22.cpo.session_service.SessionService.update_meter_values"
            ) as mock_update_meter_values,
        ):
            mock_check_meter_values_frequency.return_value = True
            process_meter_values(
                request=MagicMock(), kwh=12.5, session=OCPISessionFactory()
            )

            mock_update_meter_values.assert_called_once()

    @pytest.mark.django_db
    def test_process_meter_values_blocks_update_when_insufficient_time_elapsed(
        self,
    ):
        with patch(
            "ocpi22.cpo.api.is_meter_value_frequency_within_limit"
        ) as mock_check_meter_values_frequency:
            mock_check_meter_values_frequency.return_value = False
            result = process_meter_values(
                request=MagicMock(), kwh=12.5, session=OCPISessionFactory()
            )

            assert (
                result.data.get("status_text")
                == "Meter values received too frequently, skipping update"
            )


class TestProcessMeterValuesCalculations:
    @pytest.mark.django_db
    def test_process_meter_values_calculates_kwh_delta_correctly(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        credentials = CredentialsFactory(meter_value_frequency=None)
        CredentialsRoleFactory(
            country_code="US", party_id="CPO", credentials=credentials
        )
        session = OCPISessionFactory(
            connector=connector,
            status=Session.ACTIVE,
            start_kwh=10.5,
            credentials=credentials,
        )
        mock_request = MagicMock()

        with patch.object(session, "send_updates"):
            result = process_meter_values(
                request=mock_request, kwh=15.75, session=session
            )

            session.refresh_from_db()
            assert session.stop_kwh == 15.75
            assert result.status_code == 200

            charging_period = session.chargingperiods.first()
            energy_dimension = charging_period.dimensions.filter(type="ENERGY").first()
            assert energy_dimension.volume == Decimal("5.25")

    @pytest.mark.django_db
    def test_process_meter_values_sets_start_kwh_when_session_start_is_zero(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        credentials = CredentialsFactory(meter_value_frequency=None)
        CredentialsRoleFactory(
            country_code="US", party_id="CPO", credentials=credentials
        )
        session = OCPISessionFactory(
            connector=connector,
            status=Session.ACTIVE,
            start_kwh=0.0,
            credentials=credentials,
        )
        mock_request = MagicMock()

        with patch.object(session, "send_updates"):
            _ = process_meter_values(request=mock_request, kwh=15.75, session=session)

            session.refresh_from_db()
            assert session.start_kwh == 15.75


class TestFindTokenByUid:
    @pytest.mark.django_db
    def test_find_token_by_uid_returns_none_when_no_token_exists(self):
        result = _find_token_by_uid("NONEXISTENT_TOKEN")

        assert result is None

    @pytest.mark.django_db
    def test_find_token_by_uid_returns_token_when_exact_match_exists(self):
        token = TokenFactory(uid="RANDOMGIBERISH9898")

        result = _find_token_by_uid("RANDOMGIBERISH9898")

        assert result == token


class TestProcessAuthorizeData:
    def test_process_authorize_data_exits_early_when_decode_message_fails(
        self, auth_request_message
    ):
        auth_request_message.payload = b"\x80"

        with (
            patch(
                "ocpi22.cpo.mqtt.services._decode_message", return_value=None
            ) as mock_decode_message,
            patch(
                "ocpi22.cpo.mqtt.services._authorize_and_publish"
            ) as mock_authorize_and_publish,
        ):
            result = process_authorize_data(auth_request_message)

            assert result is None
            mock_decode_message.assert_called_once_with(auth_request_message)
            mock_authorize_and_publish.assert_not_called()

    def test_process_authorize_data_exits_early_when_data_validation_fails(
        self, auth_request_message, caplog
    ):
        auth_request_message.payload = b'{"invalid_data": "some_value"}'

        result = process_authorize_data(auth_request_message)

        assert result is None
        assert any(
            f"Failed to parse message from topic {auth_request_message.topic}"
            in record.message
            for record in caplog.records
        )

    def test_process_authorize_data_calls_authorize_and_publish_when_validation_succeeds(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        expected_token_auth = TokenAuthorizationMessageIn.model_validate(
            decoded_message
        )

        with patch(
            "ocpi22.cpo.mqtt.services._authorize_and_publish"
        ) as mock_authorize_and_publish:
            result = process_authorize_data(auth_request_message)

            mock_authorize_and_publish.assert_called_once()
            call_args = mock_authorize_and_publish.call_args[0]
            assert call_args[0].token_id == expected_token_auth.token_id
            assert call_args[0].evse_id == expected_token_auth.evse_id
            assert call_args[0].correlation_id == expected_token_auth.correlation_id
            assert call_args[1] == auth_request_message.topic
            assert result is None


class TestAuthorizeAndPublish:
    @pytest.mark.django_db
    def test_authorize_and_publish_publishes_not_allowed_when_evse_not_found(
        self, auth_request_message, caplog
    ):
        caplog.clear()
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=None),
            patch(
                "ocpi22.cpo.mqtt.services._publish_not_allowed_auth_response"
            ) as mock_publish_not_allowed,
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            assert any(
                f"Unable to authorize token from MQTT on topic {auth_request_message.topic}: EVSE with ID '{token_auth_message.evse_id}' not found"
                in record.message
                for record in caplog.records
            )

    @pytest.mark.django_db
    def test_authorize_and_publish_publishes_not_allowed_when_authorization_not_allowed(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)
        token = TokenFactory(uid=token_auth_message.token_id)

        mock_authorization = MagicMock(spec=TokenAuthorization)
        mock_authorization.allowed = AuthorizationEnum.NOT_ALLOWED

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=evse),
            patch("ocpi22.cpo.mqtt.services._find_token_by_uid", return_value=token),
            patch(
                "ocpi22.cpo.mqtt.services.authorize_token",
                return_value=mock_authorization,
            ),
            patch(
                "ocpi22.cpo.mqtt.services._publish_not_allowed_auth_response"
            ) as mock_publish_not_allowed,
            patch(
                "ocpi22.cpo.mqtt.services.create_and_save_session"
            ) as mock_create_session,
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            mock_create_session.assert_not_called()

    @pytest.mark.django_db
    def test_authorize_and_publish_publishes_not_allowed_when_authorization_is_none(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)
        token = TokenFactory(uid=token_auth_message.token_id)

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=evse),
            patch("ocpi22.cpo.mqtt.services._find_token_by_uid", return_value=token),
            patch("ocpi22.cpo.mqtt.services.authorize_token", return_value=None),
            patch(
                "ocpi22.cpo.mqtt.services._publish_not_allowed_auth_response"
            ) as mock_publish_not_allowed,
            patch(
                "ocpi22.cpo.mqtt.services.create_and_save_session"
            ) as mock_create_session,
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            mock_create_session.assert_not_called()

    @pytest.mark.django_db
    def test_authorize_and_publish_creates_session_and_publishes_allowed_when_authorization_succeeds(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)
        token = TokenFactory(uid=token_auth_message.token_id)
        session = Session(uid="test-session-123")

        mock_authorization = MagicMock(spec=TokenAuthorization)
        mock_authorization.allowed = AuthorizationEnum.ALLOWED

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=evse),
            patch("ocpi22.cpo.mqtt.services._find_token_by_uid", return_value=token),
            patch(
                "ocpi22.cpo.mqtt.services.authorize_token",
                return_value=mock_authorization,
            ),
            patch(
                "ocpi22.cpo.mqtt.services.create_and_save_session", return_value=session
            ) as mock_create_session,
            patch(
                "ocpi22.cpo.mqtt.services.publish_auth_response"
            ) as mock_publish_auth_response,
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            mock_create_session.assert_called_once_with(mock_authorization, evse)
            mock_publish_auth_response.assert_called_once()

            published_message = mock_publish_auth_response.call_args[0][0]
            assert published_message.allowed == AuthorizationEnum.ALLOWED
            assert published_message.correlation_id == token_auth_message.correlation_id
            assert published_message.session_id == session.uid

    @pytest.mark.django_db
    def test_authorize_and_publish_uses_token_string_when_token_not_found_in_database(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)

        mock_authorization = MagicMock(spec=TokenAuthorization)
        mock_authorization.allowed = AuthorizationEnum.ALLOWED
        session = Session(uid="test-session-456")

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=evse),
            patch("ocpi22.cpo.mqtt.services._find_token_by_uid", return_value=None),
            patch(
                "ocpi22.cpo.mqtt.services.authorize_token",
                return_value=mock_authorization,
            ) as mock_authorize_token,
            patch(
                "ocpi22.cpo.mqtt.services.create_and_save_session", return_value=session
            ),
            patch("ocpi22.cpo.mqtt.services.publish_auth_response"),
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            token_reference = TokenReference(uid='TEST_TOKEN_123', adhoc=True, token=None)
            mock_authorize_token.assert_called_once_with(
                token_reference, evse.location, evse_id=evse.evse_id
            )

    @pytest.mark.django_db
    def test_authorize_and_publish_publishes_not_allowed_when_exception_occurs(
        self, auth_request_message, caplog
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)

        with (
            patch("ocpi22.cpo.mqtt.services.find_our_evse", return_value=evse),
            patch("ocpi22.cpo.mqtt.services._find_token_by_uid", return_value=None),
            patch(
                "ocpi22.cpo.mqtt.services.authorize_token",
                side_effect=Exception("Test exception"),
            ),
            patch(
                "ocpi22.cpo.mqtt.services._publish_not_allowed_auth_response"
            ) as mock_publish_not_allowed,
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            assert any(
                f"MQTT authorization failed on topic {auth_request_message.topic}"
                in record.message
                for record in caplog.records
            )


class TestPublishNotAllowedAuthResponse:
    def test_publish_not_allowed_auth_response_creates_correct_message(self):
        correlation_id = "test-correlation-123"

        with patch("ocpi22.cpo.mqtt.services.publish_auth_response") as mock_publish:
            from ocpi22.cpo.mqtt.services import _publish_not_allowed_auth_response

            _publish_not_allowed_auth_response(correlation_id)

            mock_publish.assert_called_once()
            published_message = mock_publish.call_args[0][0]
            assert isinstance(published_message, TokenAuthorizationResponse)
            assert published_message.allowed == AuthorizationEnum.NOT_ALLOWED
            assert published_message.correlation_id == correlation_id
            assert published_message.session_id is None


@pytest.mark.django_db
class TestCreateAndSaveSession:
    def test_create_and_save_session_creates_session_with_token_dict_authorization(
        self,
    ):
        get_credentialsrole.cache_clear()
        location = LocationFactory()
        evse = EvseFactory(location=location)
        msp_credentialsrole = CredentialsRoleFactory(country_code="FI", party_id="MSP")

        token_dict = {
            "uid": "test-token-123",
            "valid": True,
            "type": "RFID",
            "contract_id": "contract-456",
            "country_code": "FI",
            "party_id": "MSP",
            "billed_to": "FI*MSP",
            "ocpi_master": msp_credentialsrole,
        }

        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=token_dict,
            responding_party="FI*MSP",
            authorization_reference="auth-ref-789",
            auth_method="AUTH_REQUEST",
            msp=msp_credentialsrole,
            billed_to=msp_credentialsrole.get_party(),
        )

        result = create_and_save_session(authorization, evse)

        assert isinstance(result, Session)
        assert result.authorization_reference == "auth-ref-789"
        assert result.auth_method == "AUTH_REQUEST"
        assert result.billed_to == msp_credentialsrole
        assert result.status == Session.PENDING
        assert result.evse == evse
        assert result.connector is None
        assert result.location == evse.location
        assert result.ocpi_master == location.ocpi_master
        assert result.cdr_token.uid == "test-token-123"
        assert result.cdr_token.token_type == "RFID"
        assert result.cdr_token.contract_id == "contract-456"

    def test_create_and_save_session_handles_missing_contract_id_in_token_dict(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="DE", party_id="EMO")

        token_dict = {
            "uid": "test-token-456",
            "valid": False,
            "type": "APP_USER",
            "country_code": "DE",
            "party_id": "EMO",
            "billed_to": "DE*EMO",
            "ocpi_master": credentials_role,
        }

        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=token_dict,
            responding_party="DE*EMO",
            authorization_reference="auth-ref-123",
            auth_method="WHITELIST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert result.cdr_token.contract_id == "-"
        assert result.cdr_token.uid == "test-token-456"
        assert result.cdr_token.token_type == "APP_USER"
        assert result.auth_method == "WHITELIST"

    def test_create_and_save_session_with_token_object_authorization(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory()
        token = TokenFactory(uid="token-obj-789", contract_id="contract-999")

        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=token,
            responding_party=str(credentials_role.get_party()),
            authorization_reference="auth-ref-obj",
            auth_method="COMMAND",
            msp=credentials_role,
        )

        result = create_and_save_session(authorization, evse)

        assert isinstance(result, Session)
        assert result.authorization_reference == "auth-ref-obj"
        assert result.auth_method == "COMMAND"
        assert result.cdr_token.uid == token.uid
        assert result.cdr_token.contract_id == token.contract_id
        assert result.cdr_token.token_type == token.type

    def test_create_and_save_session_creates_session_with_pending_status(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="NL", party_id="ABC")

        token_dict = {
            "uid": "status-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": "NL",
            "party_id": "ABC",
            "billed_to": "NL*ABC",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="NL*ABC",
            authorization_reference="status-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert result.status == Session.PENDING

    def test_create_and_save_session_sets_evse_and_location_relationships_correctly(
        self,
    ):
        location = LocationFactory(uid="location-123")
        evse = EvseFactory(location=location, uid="evse-456")
        credentials_role = CredentialsRoleFactory(country_code="BE", party_id="XYZ")

        token_dict = {
            "uid": "evse-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": "BE",
            "party_id": "XYZ",
            "billed_to": "BE*XYZ",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="BE*XYZ",
            authorization_reference="evse-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert result.evse.uid == evse.uid
        assert result.location.uid == location.uid
        assert result.connector is None

    def test_create_and_save_session_returns_session_object_with_generated_uid(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="FR", party_id="EDF")

        token_dict = {
            "uid": "return-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": "FR",
            "party_id": "EDF",
            "billed_to": "FR*EDF",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="FR*EDF",
            authorization_reference="return-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert isinstance(result, Session)
        assert result.uid is not None

    def test_create_and_save_session_with_explicit_billed_to_parameter(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="AT", party_id="ENI")

        token_dict = {
            "uid": "billed-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": "AT",
            "party_id": "ENI",
            "billed_to": "AT*ENI",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="AT*ENI",
            authorization_reference="billed-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to="AT*ENI",
        )

        result = create_and_save_session(authorization, evse)

        assert result.authorization_reference == "billed-auth-ref"
        assert result.auth_method == "AUTH_REQUEST"

    def test_create_and_save_session_sets_credentials_and_master_relationships(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        hub_credentials = CredentialsFactory()
        hub_credentials_role = CredentialsRoleFactory(
            credentials=hub_credentials,
            country_code="FR",
            party_id="007",
            business_details__name="Gireve",
        )
        msp_credentials_role = CredentialsRoleFactory(
            country_code="FR",
            party_id="MSP",
            business_details__name="Le Francaise MSP magnifique",
        )

        token_dict = {
            "uid": "credentials-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": msp_credentials_role.country_code,
            "party_id": msp_credentials_role.party_id,
            "billed_to": str(msp_credentials_role.get_party()),
            "ocpi_master": msp_credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party=str(hub_credentials_role.get_party()),
            authorization_reference="credentials-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=msp_credentials_role,
            billed_to=str(msp_credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert result.credentials == hub_credentials
        assert result.billed_to == msp_credentials_role
        assert result.ocpi_master == location.ocpi_master

    def test_create_and_save_session_creates_cdr_token_with_correct_ocpi_master(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="CH", party_id="SWI")

        token_dict = {
            "uid": "cdr-test-token",
            "valid": True,
            "type": "RFID",
            "contract_id": "cdr-contract",
            "country_code": "CH",
            "party_id": "SWI",
            "billed_to": "CH*SWI",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="CH*SWI",
            authorization_reference="cdr-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        assert result.cdr_token.ocpi_master == credentials_role
        assert result.cdr_token.uid == "cdr-test-token"
        assert result.cdr_token.contract_id == "cdr-contract"
        assert result.cdr_token.token_type == "RFID"

    def test_create_and_save_session_persists_session_to_database(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        credentials_role = CredentialsRoleFactory(country_code="IT", party_id="ENE")

        token_dict = {
            "uid": "persist-test-token",
            "valid": True,
            "type": "RFID",
            "country_code": "IT",
            "party_id": "ENE",
            "billed_to": "IT*ENE",
            "ocpi_master": credentials_role,
        }
        authorization = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(**token_dict),
            responding_party="IT*ENE",
            authorization_reference="persist-auth-ref",
            auth_method="AUTH_REQUEST",
            msp=credentials_role,
            billed_to=str(credentials_role.get_party()),
        )

        result = create_and_save_session(authorization, evse)

        saved_session = Session.objects.get(uid=result.uid)
        assert saved_session.authorization_reference == "persist-auth-ref"
        assert saved_session.cdr_token.uid == "persist-test-token"
        assert saved_session.status == Session.PENDING

    @pytest.mark.django_db
    def test_authorize_and_publish_passes_location_instead_of_evse_to_authorize_token(
        self, auth_request_message
    ):
        decoded_message = orjson.loads(auth_request_message.payload)
        token_auth_message = TokenAuthorizationMessageIn.model_validate(decoded_message)

        location = LocationFactory()
        evse = EvseFactory(location=location, uid=token_auth_message.evse_id)
        token = TokenFactory(uid=token_auth_message.token_id)

        mock_authorization = MagicMock(spec=TokenAuthorization)
        mock_authorization.allowed = AuthorizationEnum.ALLOWED

        with (
            patch(
                "ocpi22.cpo.mqtt.services.authorize_token",
                return_value=mock_authorization,
            ) as mock_authorize_token,
            patch("ocpi22.cpo.mqtt.services.publish_auth_response"),
        ):
            _authorize_and_publish(token_auth_message, auth_request_message.topic)
            token_reference = TokenReference(
                uid=token.uid, adhoc=False, token=token
            )
            mock_authorize_token.assert_called_once_with(
                token_reference, evse.location, evse_id=evse.evse_id
            )


@pytest.mark.django_db
class TestCheckMeterValuesFrequency:
    @pytest.fixture
    def session(self):
        return OCPISessionFactory(
            uid="meter-value-frequency-test-session",
            credentials=CredentialsFactory(meter_value_frequency=60),
        )

    def test_returns_true_when_meter_value_frequency_none(self, session):
        session.credentials.meter_value_frequency = None
        session.credentials.save()
        assert is_meter_value_frequency_within_limit(session, datetime.now()) is True

    @patch("ocpi22.cpo.api.get_cached_session")
    def test_returns_true_when_no_cached_session(self, mock_get_cached, session):
        mock_get_cached.return_value = None
        assert is_meter_value_frequency_within_limit(session, datetime.now()) is True

    @patch("ocpi22.cpo.api.get_cached_session")
    def test_returns_false_when_elapsed_time_less_than_frequency(
        self, mock_get_cached, session
    ):
        last_update = datetime.now(pytz.utc) - timedelta(seconds=30)
        cached = Mock(model=CachedSession)
        cached.meter_value_update_date_time = last_update
        mock_get_cached.return_value = cached
        now = last_update + timedelta(seconds=10)
        assert is_meter_value_frequency_within_limit(session, now) is False

    @patch("ocpi22.cpo.api.get_cached_session")
    def test_returns_true_when_elapsed_time_exceeds_frequency(
        self, mock_get_cached, session
    ):
        last_update = datetime.now(pytz.utc) - timedelta(seconds=120)
        cached = Mock(model=CachedSession)
        cached.meter_value_update_date_time = last_update
        mock_get_cached.return_value = cached
        now = last_update + timedelta(seconds=121)
        assert is_meter_value_frequency_within_limit(session, now) is True

    @patch("ocpi22.cpo.api.get_cached_session")
    def test_naive_datetime_is_localized_to_utc(self, mock_get_cached, session):
        last_update = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
        cached = Mock()
        cached.meter_value_update_date_time = last_update
        mock_get_cached.return_value = cached
        now = datetime(2024, 1, 1, 12, 0, 30)
        session.credentials.meter_value_frequency = 60
        assert is_meter_value_frequency_within_limit(session, now) is False
