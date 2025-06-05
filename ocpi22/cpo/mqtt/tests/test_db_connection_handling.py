from unittest.mock import MagicMock

import pytest
from django.db.utils import OperationalError as DjangoOperationalError

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
                raise DjangoOperationalError("(2006, 'MySQL server has gone away')")
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
            raise DjangoOperationalError("Some other database error")

        with pytest.raises(DjangoOperationalError, match="Some other database error"):
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

    def test_decorator_retries_on_mysql_error_code_2006(self):
        call_count = 0

        @ensure_db_connection
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DjangoOperationalError("(2006, 'Server has gone away')")
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
                raise DjangoOperationalError("MySQL server has gone away")
            return "retried_successfully"

        result = test_function()
        assert result == "retried_successfully"
        assert call_count == 2
