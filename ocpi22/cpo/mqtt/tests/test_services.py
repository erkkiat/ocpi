import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import orjson
import pytest
import time_machine
from kombu.exceptions import OperationalError

from ocpi22.choices import AuthorizationEnum
from ocpi22.cpo.api import process_meter_values
from ocpi22.cpo.mqtt.schemas import (
    MeterValues,
    EvseStatusUpdate,
    TokenAuthorizationMessageIn,
    TokenAuthorizationResponse,
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
from ocpiconnector.party import Party


class TestMqttServices:
    def test_decode_message_success(self, smappee_status_update_message):
        assert _decode_message(smappee_status_update_message) == (
            '{"evse_uid":"D80B60C1-751E-43B5-868B-9A60A41C5456", "status":"AVAILABLE"}'
        )

    def test_decode_message_returns_none_on_unicode_error(
        self, smappee_status_update_message, caplog
    ):
        smappee_status_update_message.payload = b"\x80"
        assert _decode_message(smappee_status_update_message) is None
        assert any(
            f"Failed to decode {smappee_status_update_message.topic} message"
            in record.message
            for record in caplog.records
        )

    def test_process_meter_values_data_exits_early_if_decode_message_fails(
        self, smappee_meter_message
    ):
        smappee_meter_message.payload = b"\x80"
        with (
            patch(
                "ocpi22.cpo.mqtt.services._decode_message", return_value=None
            ) as mock_decode_message,
            patch("ocpi22.tasks.send_ocpi_request") as mock_process_meter_values_task,
        ):
            assert process_meter_values_data(smappee_meter_message) is None
        mock_decode_message.assert_called_once_with(smappee_meter_message)
        mock_process_meter_values_task.assert_not_called()

    def test_process_meter_values_update_returns_none_when_data_validation_fails(
        self, smappee_meter_message, caplog
    ):
        caplog.set_level(logging.ERROR, logger="ocpi22.cpo.mqtt.services")
        smappee_meter_message.payload = b'{"invalid_data": "94f5993d-232a-4916-a801-4e408c24c9cc", "kw": 1.1, "soc": 1.1, "power": 2.2, timestamp": "2022-02-22T22:22:22"}'
        assert process_meter_values_data(smappee_meter_message) is None
        assert any(
            f"Failed to validate {smappee_meter_message.topic} message"
            in record.message
            for record in caplog.records
        )

    @pytest.mark.skip
    def test_process_meter_values_update_fails_when_celery_kwargs_not_satisfied(
        self, smappee_meter_message, caplog
    ):
        meter_values = MagicMock(spec=MeterValues)
        meter_values.model_dump.return_value = (
            '{"kw": 1.1, "soc": 1.1, "power": 2.2, timestamp": "2022-02-22T22:22:22"}'
        )
        with patch.object(
            MeterValues, "model_validate_json", return_value=meter_values
        ):
            with patch.object(
                process_meter_values,
                "apply_async",
                side_effect=OperationalError("Some error from celery"),
            ):
                assert process_meter_values_data(smappee_meter_message) is None
                assert any(
                    "Celery operational error" in record.message
                    for record in caplog.records
                )

    @pytest.mark.skip
    def test_process_meter_values_update_fails_when_unexpected_error_occurs(
        self, smappee_meter_message, caplog
    ):
        meter_values = MagicMock(spec=MeterValues)
        meter_values.model_dump.return_value = '{"a": "b"}'
        with patch.object(
            MeterValues, "model_validate_json", return_value=meter_values
        ):
            with patch.object(
                process_meter_values,
                "apply_async",
                side_effect=Exception("Some unexpected error"),
            ):
                assert process_meter_values_data(smappee_meter_message) is None
                assert any(
                    "An unexpected error occurred" in record.message
                    for record in caplog.records
                )

    @time_machine.travel("2025-02-11 09:00:00", tick=False)
    @pytest.mark.django_db
    def test_mqtt_meter_values_calls_send_background_update_successfully(
        self,
        smappee_meter_message,
        msp_credentials_with_endpoints,
        hubject_credentialsrole,
    ):
        meter_values = MagicMock(spec=MeterValues)
        decoded_message = _decode_message(smappee_meter_message)
        message_dict = orjson.loads(decoded_message)
        message_dict["timestamp"] = datetime.fromisoformat(message_dict["timestamp"])
        meter_values.model_dump.return_value = message_dict
        location = LocationFactory(uid="LOCATION1")
        evse = EvseFactory(location=location, uid="EVSE1")
        tariff = TariffFactory(uid="TARIFF1")
        connector = ConnectorFactory(uid="1", evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            uid="94f5993d-232a-4916-a801-4e408c24c9cc", start_kwh=0, connector=connector
        )
        with patch.object(
            MeterValues, "model_validate_json", return_value=meter_values
        ):
            with patch(
                "ocpi22.ocpi.util.OcpiModule.send_background_update"
            ) as mock_send_background_update:
                process_meter_values_data(smappee_meter_message)
                mock_send_background_update.assert_called_once_with(
                    {
                        "country_code": "FI",
                        "party_id": "CPO",
                        "id": "94f5993d-232a-4916-a801-4e408c24c9cc",
                        "start_date_time": "2021-01-01T10:00:00Z",
                        "end_date_time": "2021-01-01T12:00:00Z",
                        "kwh": 1.1,
                        "charging_periods": [
                            {
                                "start_date_time": "2021-01-01T10:00:00Z",
                                "tariff_id": "TARIFF1",
                                "dimensions": [
                                    {"type": "ENERGY", "volume": "1.1000"},
                                    {"type": "STATE_OF_CHARGE", "volume": "1.1000"},
                                    {"type": "POWER", "volume": "2.2000"},
                                    {"type": "TIME", "volume": "10020.3728"},
                                ],
                            }
                        ],
                        "cdr_token": OrderedDict(
                            [
                                ("country_code", "FI"),
                                ("party_id", "MSP"),
                                ("uid", "DEADC0DE"),
                                ("type", "RFID"),
                                ("contract_id", "CONTRACT-12345"),
                            ]
                        ),
                        "auth_method": "AUTH_REQUEST",
                        "authorization_reference": "AUTHORIZATION-12345",
                        "location_id": "LOCATION1",
                        "evse_uid": "EVSE1",
                        "connector_id": "1",
                        "currency": "EUR",
                        "total_cost": OrderedDict(
                            [("excl_vat", 0.8), ("incl_vat", 0.9)]
                        ),
                        "status": "ACTIVE",
                        "last_updated": "2025-02-11T09:00:00Z",
                    },
                    "https://localhost/ocpi/sessions/FI/CPO/94f5993d-232a-4916-a801-4e408c24c9cc",
                    "QUJD",
                    to=Party(country_code="FI", party_id="MSP"),
                    sender=Party(country_code="FI", party_id="CPO"),
                    method="put",
                    credentials=session.credentials,
                )

    @pytest.mark.django_db
    def test_meter_values_update_data_calls_send_ocpi_message_with_put_only(
        self, smappee_meter_message, msp_credentials_with_endpoints
    ):
        meter_values = MagicMock(spec=MeterValues)
        decoded_message = _decode_message(smappee_meter_message)
        message_dict = orjson.loads(decoded_message)
        message_dict["timestamp"] = datetime.fromisoformat(message_dict["timestamp"])
        meter_values.model_dump.return_value = message_dict
        OCPISessionFactory(uid="94f5993d-232a-4916-a801-4e408c24c9cc")

        with (
            patch(
                "ocpi22.ocpi.util.OcpiModule.send_background_update"
            ) as mock_send_background_update,
        ):
            process_meter_values_data(smappee_meter_message)
            mock_send_background_update.assert_called_once()
            assert mock_send_background_update.call_args.kwargs["method"] == "put"

    @pytest.mark.django_db
    def test_meter_values_from_wouter_successfully(
        self, smappee_meter_message_from_wouter
    ):
        decoded_message = _decode_message(smappee_meter_message_from_wouter)
        message_dict = orjson.loads(decoded_message)
        session_id = message_dict.get("session_id")
        OCPISessionFactory(
            uid=session_id,
            start_date_time=datetime.fromisoformat(message_dict.get("timestamp"))
            - timedelta(hours=0.76),
        )
        process_meter_values_data(smappee_meter_message_from_wouter)
        session = Session.objects.get(uid=session_id)
        assert session.kwh == 125
        assert list(
            session.chargingperiods.all()[0].dimensions.values_list("type", "volume")
        ) == [
            ("ENERGY", Decimal("125.0000")),
            ("POWER", Decimal("22.0000")),
            ("TIME", Decimal("0.7600")),
        ]

    @patch("ocpi22.cpo.mqtt.services._decode_message", return_value=None)
    @patch.object(EvseStatusUpdate, attribute="model_validate_json")
    @patch.object(save_and_send_evse_status_updates, attribute="apply_async")
    def test_process_status_updates_data_exits_early_if_decode_message_fails(
        self,
        mock_apply_async,
        mock_model_validate_json,
        mock_decode_message,
        smappee_status_update_message,
    ):
        smappee_status_update_message.payload = b"\x80"
        assert process_status_update_data(smappee_status_update_message) is None
        mock_decode_message.assert_called_once_with(smappee_status_update_message)
        mock_model_validate_json.assert_not_called()
        mock_apply_async.assert_not_called()

    def test_process_status_update_data_returns_none_when_data_validation_fails(
        self, smappee_status_update_message, caplog
    ):
        smappee_status_update_message.payload = b'{"invalid_data": "94f5993d-232a"}'
        assert process_meter_values_data(smappee_status_update_message) is None
        # caplog.set_level(logging.INFO, logger="ocpi22.cpo.mqtt.services")

        assert any(
            f"Failed to validate {smappee_status_update_message.topic} message"
            in record.message
            for record in caplog.records
        )

    def test_process_status_update_data_fails_when_celery_kwargs_not_satisfied(
        self, smappee_status_update_message, caplog
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        evse_status.model_dump.return_value = '{"unknown_field" "d80b60c1-751e-43b5-868b-9a60a41c5456", "status" "AVAILABLE"}'
        with patch.object(
            EvseStatusUpdate, "model_validate_json", return_value=evse_status
        ):
            with patch.object(
                save_and_send_evse_status_updates,
                "apply_async",
                side_effect=OperationalError("Some error from celery"),
            ):
                assert process_status_update_data(smappee_status_update_message) is None
                assert any(
                    "Celery operational error" in record.message
                    for record in caplog.records
                )

    def test_process_status_update_data_fails_when_unexpected_error_occurs(
        self, smappee_status_update_message, caplog, db
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        evse_status.model_dump.return_value = (
            '{"invalid": "d80b60c1-751e-43b5-868b-9a60a41c5456", "status": "AVAILABLE"}'
        )
        with patch.object(
            EvseStatusUpdate, "model_validate_json", return_value=evse_status
        ):
            with patch.object(
                save_and_send_evse_status_updates,
                "apply_async",
                side_effect=Exception("Some unexpected error"),
            ):
                assert process_status_update_data(smappee_status_update_message) is None
                assert any(
                    "An unexpected error occurred" in record.message
                    for record in caplog.records
                )

    def test_process_status_update_data_calls_save_and_send_evse_status_updates_celery_task_successfully(
        self, smappee_status_update_message
    ):
        evse_status = MagicMock(spec=EvseStatusUpdate)
        decoded_message = _decode_message(smappee_status_update_message)
        message_dict = orjson.loads(decoded_message)
        evse_status.model_dump.return_value = message_dict
        with patch.object(
            EvseStatusUpdate, "model_validate_json", return_value=evse_status
        ):
            with patch.object(
                save_and_send_evse_status_updates, "apply_async"
            ) as mock_save_and_send_evse_status_updates_task:
                process_status_update_data(smappee_status_update_message)
                mock_save_and_send_evse_status_updates_task.assert_called_once_with(
                    kwargs=message_dict, expires=35
                )

    @pytest.mark.django_db
    def test_process_meter_values_calculates_kwh_delta_after_decimal_conversion_in_save(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.5
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


class TestAuthorizeDataOverMqtt:
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
    def test_process_authorize_data_exits_early_if_decode_message_fails(
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

            mock_decode_message.assert_called_once_with(auth_request_message)
            mock_authorize_and_publish.assert_not_called()
            assert result is None

    def test_process_authorize_data_returns_none_when_data_validation_fails(
        self, auth_request_message, caplog
    ):
        auth_request_message.payload = b'{"invalid_data": "some_value"}'
        result = process_authorize_data(auth_request_message)

        assert result is None
        assert any(
            f"Failed to parse {auth_request_message.topic} message" in record.message
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
            assert call_args[1] == auth_request_message
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
            _authorize_and_publish(token_auth_message, auth_request_message)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            assert any(
                f"Unable to authorize token from MQTT message: EVSE with ID '{token_auth_message.evse_id}' not found"
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
            _authorize_and_publish(token_auth_message, auth_request_message)

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
            _authorize_and_publish(token_auth_message, auth_request_message)

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
            _authorize_and_publish(token_auth_message, auth_request_message)

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
            _authorize_and_publish(token_auth_message, auth_request_message)

            mock_authorize_token.assert_called_once_with(
                token_auth_message.token_id, evse.location, evse_id=evse.evse_id
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
            _authorize_and_publish(token_auth_message, auth_request_message)

            mock_publish_not_allowed.assert_called_once_with(
                token_auth_message.correlation_id
            )
            assert any(
                "MQTT authorization failed miserably for auth message" in record.message
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
            token=AdhocToken(**token_dict),
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
            token=AdhocToken(**token_dict),
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
        assert len(result.uid) > 0

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
            _authorize_and_publish(token_auth_message, auth_request_message)
            mock_authorize_token.assert_called_once_with(
                token, evse.location, evse_id=evse.evse_id
            )
