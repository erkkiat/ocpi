from unittest.mock import MagicMock, patch

import pytest
from django.db.utils import OperationalError, InterfaceError

from ocpi22.cpo.mqtt.services import (
    ensure_db_connection,
    process_meter_values_data,
    process_status_update_data,
)


class TestDatabaseConnectionHandling:
    def test_decorator_retries_on_mysql_server_gone_away_error(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("(2006, 'MySQL server has gone away')")
            return "success"

        result = test_function()
        assert result == "success"
        assert call_count == 2

    def test_decorator_does_not_retry_other_database_errors(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            raise OperationalError("Some other database error")

        with pytest.raises(OperationalError, match="Some other database error"):
            test_function()

        assert call_count == 1

    def test_decorator_does_not_catch_non_database_errors(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Some application error")

        with pytest.raises(ValueError, match="Some application error"):
            test_function()

        assert call_count == 1

    def test_decorator_allows_successful_execution_without_retry(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = test_function()
        assert result == "success"
        assert call_count == 1

    def test_decorator_retries_on_mysql_error_code_2006(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("(2006, 'Server has gone away')")
            return "retried_successfully"

        result = test_function()
        assert result == "retried_successfully"
        assert call_count == 2

    def test_decorator_retries_on_server_gone_away_text_without_error_code(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("MySQL server has gone away")
            return "retried_successfully"

        result = test_function()
        assert result == "retried_successfully"
        assert call_count == 2

    def test_decorator_retries_on_error_code_2013(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError(
                    "(2013, 'Lost connection to MySQL server during query')"
                )
            return "retried_successfully"

        result = test_function()
        assert result == "retried_successfully"
        assert call_count == 2

    def test_decorator_handles_interface_error(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise InterfaceError("(2006, 'MySQL server has gone away')")
            return "retried_successfully"

        result = test_function()
        assert result == "retried_successfully"
        assert call_count == 2

    def test_decorator_raises_on_retry_failure(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            raise OperationalError("(2006, 'MySQL server has gone away')")

        with pytest.raises(OperationalError):
            test_function()

        assert call_count == 2

    def test_decorator_handles_case_insensitive_error_matching(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("(2006, 'MYSQL SERVER HAS GONE AWAY')")
            return "case_insensitive_success"

        result = test_function()
        assert result == "case_insensitive_success"
        assert call_count == 2

    def test_decorator_preserves_function_arguments_and_return_values(self):
        @ensure_db_connection
        def test_function(arg1, arg2, kwarg1=None):
            return f"{arg1}-{arg2}-{kwarg1}"

        result = test_function("test", "value", kwarg1="param")
        assert result == "test-value-param"

    @patch("ocpi22.cpo.mqtt.services.time")
    @patch("ocpi22.cpo.mqtt.services.close_old_connections")
    def test_decorator_calls_close_connections_and_sleeps_on_retry(
        self, mock_close, mock_time
    ):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("(2006, 'Server has gone away')")
            return "success"

        test_function()

        mock_close.assert_called_once()
        mock_time.sleep.assert_called_once_with(0.1)

    def test_process_meter_values_handles_invalid_utf8_message_gracefully(self):
        message = MagicMock()
        message.payload.decode.side_effect = UnicodeDecodeError(
            "utf-8", b"", 0, 1, "invalid start byte"
        )
        message.topic = "test/topic"

        result = process_meter_values_data(message)
        assert result is None

    def test_process_status_update_handles_invalid_utf8_message_gracefully(self):
        message = MagicMock()
        message.payload.decode.side_effect = UnicodeDecodeError(
            "utf-8", b"", 0, 1, "invalid start byte"
        )
        message.topic = "test/topic"

        result = process_status_update_data(message)
        assert result is None

    def test_process_meter_values_handles_invalid_json_gracefully(self):
        message = MagicMock()
        message.payload.decode.return_value = '{"invalid": json}'
        message.topic = "test/topic"

        result = process_meter_values_data(message)
        assert result is None

    def test_process_status_update_handles_invalid_json_gracefully(self):
        message = MagicMock()
        message.payload.decode.return_value = '{"invalid": json}'
        message.topic = "test/topic"

        result = process_status_update_data(message)
        assert result is None
