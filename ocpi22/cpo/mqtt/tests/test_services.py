import logging
from collections import OrderedDict
from datetime import datetime
from unittest.mock import MagicMock, patch

import orjson
import pytest
import time_machine
from kombu.exceptions import OperationalError

from ocpi22.cpo.api import process_meter_values
from ocpi22.cpo.mqtt.schemas import MeterValues, EvseStatusUpdate
from ocpi22.cpo.mqtt.services import (
    _decode_message,
    process_meter_values_data,
    process_status_update_data,
)
from ocpi22.cpo.mqtt.tasks import save_and_send_evse_status_updates
from ocpi22.tests.factories import (
    OCPISessionFactory,
    ConnectorFactory,
    LocationFactory,
    EvseFactory,
    TariffFactory,
)
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
        self, smappee_meter_message, msp_credentials_with_endpoints
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
        OCPISessionFactory(
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
                                ("uid", "CDRTOKEN-12345"),
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
                    "https://example.com/ocpi/sessions/FI/CPO/94f5993d-232a-4916-a801-4e408c24c9cc",
                    "QUJD",
                    to=Party(country_code="FI", party_id="MSP"),
                    sender=Party(country_code="FI", party_id="CPO"),
                    method="put",
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
