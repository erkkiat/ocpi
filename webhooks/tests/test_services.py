from datetime import timedelta, datetime

import pytest
from unittest.mock import Mock, patch
from django.utils import timezone
from django.core.exceptions import ValidationError
import time_machine
import requests
import responses

from webhooks.services import (
    WebhookService,
    WebhookEventService,
    WebhookExecutionService,
    WebHookExecutionError,
)
from webhooks.models import WebhookEventStatus, WebhookEventType
from webhooks.factories import (
    WebhookAuthBearerFactory,
    WebhookAuthBasicFactory,
    WebhookAuthApiKeyFactory,
    WebhookFactory,
    WebhookWithAuthFactory,
    WebhookInactiveFactory,
    WebhookEventFactory,
    WebhookEventSuccessFactory,
    WebhookEventFailedFactory,
    WebhookEventExhaustedFactory,
)


@pytest.mark.django_db
class TestWebhookService:
    def test_activate_webhook_sets_active_true_and_saves(self):
        inactive_webhook = WebhookInactiveFactory()

        result = WebhookService.activate_webhook(inactive_webhook)

        assert result.active is True
        inactive_webhook.refresh_from_db()
        assert inactive_webhook.active is True

    def test_deactivate_webhook_sets_active_false_and_saves(self):
        active_webhook = WebhookFactory()

        result = WebhookService.deactivate_webhook(active_webhook)

        assert result.active is False
        active_webhook.refresh_from_db()
        assert active_webhook.active is False

    def test_activate_webhook_returns_same_webhook_instance(self):
        webhook = WebhookInactiveFactory()

        result = WebhookService.activate_webhook(webhook)

        assert result is webhook

    def test_deactivate_webhook_returns_same_webhook_instance(self):
        webhook = WebhookFactory()

        result = WebhookService.deactivate_webhook(webhook)

        assert result is webhook

    def test_activate_webhook_persists_changes_to_database(self):
        webhook = WebhookInactiveFactory()
        updated_timestamp = webhook.updated_at + timedelta(hours=2)
        with time_machine.travel(updated_timestamp):
            WebhookService.activate_webhook(webhook)

        webhook.refresh_from_db()
        assert webhook.active
        assert webhook.updated_at == updated_timestamp

    def test_deactivate_webhook_persists_changes_to_database(self):
        webhook = WebhookFactory()

        with time_machine.travel("2024-01-15 12:00:00"):
            WebhookService.deactivate_webhook(webhook)

        webhook.refresh_from_db()
        assert not webhook.active


@pytest.mark.django_db
class TestWebhookEventService:
    @pytest.mark.parametrize(
        "timestamp,expected",
        [
            (datetime(2024, 1, 15, 10, 30, 0), "2024-01-15T10:30:00"),
            (
                datetime(2024, 6, 1, 15, 45, 30, tzinfo=timezone.utc),
                "2024-06-01T15:45:30+00:00",
            ),
        ],
    )
    def test_create_event_payload_datetime_is_serialized_as_string(
        self, timestamp, expected
    ):
        webhook = WebhookFactory()
        event_type = WebhookEventType.SESSION_STARTED
        payload = {"event_time": timestamp}

        event = WebhookEventService.create_event(webhook, event_type, payload)

        assert event.payload["event_time"] == expected

    def test_create_event_creates_webhook_event_with_provided_data(self):
        webhook = WebhookFactory()
        event_type = WebhookEventType.SESSION_STARTED
        payload = {"session_id": "SES_001", "charge_point_id": "CP_001"}

        event = WebhookEventService.create_event(webhook, event_type, payload)

        assert event.webhook == webhook
        assert event.event_type == event_type
        assert event.payload == payload
        assert event.status == WebhookEventStatus.PENDING
        assert event.attempt_count == 0

    @pytest.mark.parametrize(
        "valid_event_type",
        [
            WebhookEventType.CHARGE_POINT_STATUS_CHANGED,
            WebhookEventType.SESSION_STARTED,
            WebhookEventType.TOKEN_AUTHORIZED,
            WebhookEventType.REMOTE_START_REQUESTED,
            WebhookEventType.INVOICE_GENERATED,
        ],
    )
    def test_create_event_accepts_all_valid_event_types(self, valid_event_type):
        webhook = WebhookFactory()
        payload = {"test": "data"}

        event = WebhookEventService.create_event(webhook, valid_event_type, payload)

        assert event.event_type == valid_event_type
        assert event.status == WebhookEventStatus.PENDING

    @pytest.mark.parametrize(
        "invalid_event_type",
        [
            "invalid.event.type",
            "custom_event",
            "unknown.webhook.event",
            "",
            None,
        ],
    )
    def test_create_event_raises_validation_error_for_invalid_event_types(
        self, invalid_event_type
    ):
        webhook = WebhookFactory()
        payload = {"data": "test"}

        with pytest.raises(
            ValidationError, match=f"Invalid event type: {invalid_event_type}"
        ):
            WebhookEventService.create_event(webhook, invalid_event_type, payload)

    def test_create_event_sets_default_values_correctly(self):
        webhook = WebhookFactory()

        event = WebhookEventService.create_event(
            webhook, WebhookEventType.SESSION_STARTED, {}
        )

        assert event.status == WebhookEventStatus.PENDING
        assert event.attempt_count == 0
        assert event.last_attempted_at is None
        assert event.completed_at is None
        assert event.error_message == ""
        assert event.response_status_code is None

    def test_get_pending_events_returns_only_pending_events_for_webhook(self):
        webhook = WebhookFactory()
        other_webhook = WebhookFactory()
        pending_event = WebhookEventFactory(webhook=webhook)
        WebhookEventFailedFactory(webhook=webhook)
        WebhookEventSuccessFactory(webhook=webhook)
        WebhookEventFactory(webhook=other_webhook)

        pending_events = WebhookEventService.get_pending_events(webhook)

        assert pending_events.count() == 1
        assert pending_events.first().id == pending_event.id
        assert pending_events.first().status == WebhookEventStatus.PENDING

    def test_get_pending_events_returns_empty_queryset_when_no_pending_events(self):
        webhook = WebhookFactory()
        WebhookEventFailedFactory(webhook=webhook)
        WebhookEventSuccessFactory(webhook=webhook)

        pending_events = WebhookEventService.get_pending_events(webhook)

        assert pending_events.count() == 0

    def test_get_pending_events_excludes_exhausted_events(self):
        webhook = WebhookFactory()
        WebhookEventExhaustedFactory(webhook=webhook)

        pending_events = WebhookEventService.get_pending_events(webhook)

        assert pending_events.count() == 0

    def test_mark_attempt_started_increments_attempt_count_and_sets_timestamp(self):
        webhook_event = WebhookEventFactory()
        original_count = webhook_event.attempt_count

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_attempt_started(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.attempt_count == original_count + 1
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert (
            abs((webhook_event.last_attempted_at - expected_time).total_seconds()) < 1
        )

    def test_mark_attempt_started_preserves_other_fields(self):
        webhook_event = WebhookEventFactory(
            error_message="Previous error", response_status_code=500
        )

        WebhookEventService.mark_attempt_started(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.error_message == "Previous error"
        assert webhook_event.response_status_code == 500

    def test_mark_attempt_started_multiple_calls_increment_correctly(self):
        webhook_event = WebhookEventFactory(attempt_count=0)

        WebhookEventService.mark_attempt_started(webhook_event)
        webhook_event.refresh_from_db()
        assert webhook_event.attempt_count == 1

        WebhookEventService.mark_attempt_started(webhook_event)
        webhook_event.refresh_from_db()
        assert webhook_event.attempt_count == 2

    def test_mark_success_sets_success_status_and_completion_data(self):
        webhook_event = WebhookEventFactory()

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_success(webhook_event, status_code=201)

        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.SUCCESS
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert abs((webhook_event.completed_at - expected_time).total_seconds()) < 1
        assert webhook_event.response_status_code == 201
        assert webhook_event.error_message == ""

    def test_mark_success_uses_default_status_code_when_not_provided(self):
        webhook_event = WebhookEventFactory()

        WebhookEventService.mark_success(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.response_status_code == 200

    def test_mark_success_clears_previous_error_message(self):
        webhook_event = WebhookEventFactory(error_message="Previous error")

        WebhookEventService.mark_success(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.error_message == ""

    def test_mark_failed_sets_failed_status_when_can_retry(self):
        webhook = WebhookFactory(max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=1)
        error_message = "Connection refused"

        WebhookEventService.mark_failed(webhook_event, error_message, status_code=500)

        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert webhook_event.error_message == error_message
        assert webhook_event.response_status_code == 500
        assert webhook_event.completed_at is None

    def test_mark_failed_sets_exhausted_status_when_cannot_retry(self):
        webhook = WebhookFactory(max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=3)
        error_message = "Maximum retries exceeded"

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_failed(webhook_event, error_message)

        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.EXHAUSTED
        assert webhook_event.error_message == error_message
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert abs((webhook_event.completed_at - expected_time).total_seconds()) < 1

    def test_mark_failed_sets_status_code_to_none_when_not_provided(self):
        webhook_event = WebhookEventFactory()

        WebhookEventService.mark_failed(webhook_event, "Test error")

        webhook_event.refresh_from_db()
        assert webhook_event.response_status_code is None

    @pytest.mark.parametrize(
        "attempt_count,max_retries,expected_status",
        [
            (0, 3, WebhookEventStatus.FAILED),
            (1, 3, WebhookEventStatus.FAILED),
            (2, 3, WebhookEventStatus.FAILED),
            (3, 3, WebhookEventStatus.EXHAUSTED),
            (0, 0, WebhookEventStatus.EXHAUSTED),
            (1, 1, WebhookEventStatus.EXHAUSTED),
        ],
    )
    def test_mark_failed_sets_correct_status_based_on_retry_limits(
        self, attempt_count, max_retries, expected_status
    ):
        webhook = WebhookFactory(max_retries=max_retries)
        webhook_event = WebhookEventFactory(
            webhook=webhook, attempt_count=attempt_count
        )

        WebhookEventService.mark_failed(webhook_event, "Test error")

        webhook_event.refresh_from_db()
        assert webhook_event.status == expected_status

    def test_mark_failed_sets_completed_at_only_when_exhausted(self):
        webhook = WebhookFactory(max_retries=3)

        failed_event = WebhookEventFactory(webhook=webhook, attempt_count=1)
        WebhookEventService.mark_failed(failed_event, "Error")
        failed_event.refresh_from_db()
        assert failed_event.completed_at is None

        exhausted_event = WebhookEventFactory(webhook=webhook, attempt_count=3)
        WebhookEventService.mark_failed(exhausted_event, "Error")
        exhausted_event.refresh_from_db()
        assert exhausted_event.completed_at is not None


@pytest.mark.django_db
class TestWebhookExecutionService:
    def test_trigger_webhook_by_id_creates_event_for_active_webhook(self):
        webhook = WebhookFactory()
        event_type = WebhookEventType.SESSION_STARTED
        payload = {"session_id": "SES_001"}

        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, webhook.url, json={"success": True}, status=200)

            event = WebhookExecutionService().trigger_webhook_by_id(
                webhook.id, event_type, payload
            )

        assert event is not None
        assert event.webhook == webhook
        assert event.event_type == event_type
        assert event.payload == payload

    @patch("webhooks.services.logger")
    def test_trigger_webhook_by_id_returns_none_when_webhook_not_found(
        self, mock_logger
    ):
        non_existent_id = 99999

        result = WebhookExecutionService().trigger_webhook_by_id(
            non_existent_id, WebhookEventType.SESSION_STARTED, {"test": "data"}
        )

        assert result is None
        mock_logger.error.assert_called_once_with(
            f"Webhook with ID {non_existent_id} does not exist"
        )

    @patch("webhooks.services.logger")
    def test_trigger_webhook_by_id_returns_none_when_webhook_inactive(
        self, mock_logger
    ):
        inactive_webhook = WebhookInactiveFactory()

        result = WebhookExecutionService().trigger_webhook_by_id(
            inactive_webhook.id, WebhookEventType.SESSION_STARTED, {"test": "data"}
        )

        assert result is None
        mock_logger.warning.assert_called_once_with(
            f"Webhook with ID {inactive_webhook.id} is not active, skipping execution"
        )

    @patch("webhooks.services.logger")
    def test_trigger_webhook_by_id_returns_none_when_event_creation_fails(
        self, mock_logger
    ):
        webhook = WebhookFactory()

        with patch("webhooks.services.WebhookEventService.create_event") as mock_create:
            mock_create.side_effect = Exception("Database error")

            result = WebhookExecutionService().trigger_webhook_by_id(
                webhook.id, WebhookEventType.SESSION_STARTED, {"test": "data"}
            )

        assert result is None
        mock_logger.error.assert_called_once_with(
            f"Failed to create/execute webhook event for webhook ID {webhook.id}",
            exc_info=True,
        )

    @patch("webhooks.services.logger")
    def test_trigger_webhook_by_id_returns_none_when_execution_fails(self, mock_logger):
        webhook = WebhookFactory()

        with patch(
            "webhooks.services.WebhookExecutionService.execute_webhook_event"
        ) as mock_execute:
            mock_execute.side_effect = Exception("Execution error")

            result = WebhookExecutionService().trigger_webhook_by_id(
                webhook.id, WebhookEventType.SESSION_STARTED, {"test": "data"}
            )

        assert result is None
        mock_logger.error.assert_called_once()

    @patch("webhooks.services.logger")
    def test_trigger_webhook_by_id_logs_exception_details_when_event_creation_fails(
        self, mock_logger
    ):
        webhook = WebhookFactory()

        with patch("webhooks.services.WebhookEventService.create_event") as mock_create:
            mock_create.side_effect = ValidationError("Invalid event type")

            WebhookExecutionService().trigger_webhook_by_id(
                webhook.id, WebhookEventType.SESSION_STARTED, {"test": "data"}
            )

        mock_logger.error.assert_called_once_with(
            f"Failed to create/execute webhook event for webhook ID {webhook.id}",
            exc_info=True,
        )

    def test_execute_webhook_event_raises_error_when_event_already_completed(self):
        webhook_event = WebhookEventSuccessFactory()

        with pytest.raises(
            WebHookExecutionError, match="Cannot send to completed event"
        ):
            WebhookExecutionService().execute_webhook_event(webhook_event)

    def test_execute_webhook_event_raises_error_when_event_exhausted(self):
        webhook_event = WebhookEventExhaustedFactory()

        with pytest.raises(
            WebHookExecutionError, match="Cannot send to completed event"
        ):
            WebhookExecutionService().execute_webhook_event(webhook_event)

    @patch("webhooks.services.logger")
    def test_execute_webhook_event_raises_error_when_webhook_inactive(
        self, mock_logger
    ):
        inactive_webhook = WebhookInactiveFactory()
        webhook_event = WebhookEventFactory(webhook=inactive_webhook)

        with pytest.raises(
            WebHookExecutionError,
            match="Cannot send webhook request to a inactive webhook",
        ):
            WebhookExecutionService().execute_webhook_event(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert webhook_event.error_message == "Webhook is not active"

    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_warning_when_webhook_inactive(
        self, mock_logger
    ):
        inactive_webhook = WebhookInactiveFactory()
        webhook_event = WebhookEventFactory(webhook=inactive_webhook)

        with pytest.raises(WebHookExecutionError):
            WebhookExecutionService().execute_webhook_event(webhook_event)

        mock_logger.warning.assert_called_once_with(
            f"Cannot send webhook request to inactive webhook {inactive_webhook.id} - {inactive_webhook.url}, "
        )

    @responses.activate
    def test_execute_webhook_event_makes_successful_request_with_bearer_auth(self):
        webhook_auth = WebhookAuthBearerFactory(api_key="test-api-key-123")
        webhook = WebhookWithAuthFactory(auth=webhook_auth, timeout_seconds=30)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.SESSION_STARTED,
            payload={"session_id": "SES_001"},
        )

        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {"received": True}
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer test-api-key-123"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Accept"] == "application/json"

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS
        assert event.response_status_code == 200

    @responses.activate
    def test_execute_webhook_event_makes_successful_request_with_basic_auth(self):
        webhook_auth = WebhookAuthBasicFactory(username="testuser", password="testpass")
        webhook = WebhookWithAuthFactory(auth=webhook_auth, timeout_seconds=45)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.SESSION_STARTED,
            payload={"session_id": "SES_002"},
        )

        responses.add(responses.POST, webhook.url, json={"received": True}, status=201)

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {"received": True}
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        expected_auth_header = "Basic dGVzdHVzZXI6dGVzdHBhc3M="
        assert request.headers["Authorization"] == expected_auth_header

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS
        assert event.response_status_code == 201

    @responses.activate
    def test_execute_webhook_event_makes_successful_request_with_api_key_auth(self):
        webhook_auth = WebhookAuthApiKeyFactory(
            api_key="secret-key", api_key_header="X-Custom-Key"
        )
        webhook = WebhookWithAuthFactory(auth=webhook_auth)
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {"received": True}
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["X-Custom-Key"] == "secret-key"

    @responses.activate
    def test_execute_webhook_event_makes_request_without_auth_when_no_auth_configured(
        self,
    ):
        webhook = WebhookFactory(auth=None, timeout_seconds=15)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.TOKEN_AUTHORIZED,
            payload={"token_id": "TOK_001"},
        )

        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {"received": True}
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert "Authorization" not in request.headers

    @responses.activate
    def test_execute_webhook_event_increments_attempt_count_before_sending_request(
        self,
    ):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        WebhookExecutionService().execute_webhook_event(event)

        event.refresh_from_db()
        assert event.attempt_count == 2

    @responses.activate
    @pytest.mark.parametrize(
        "status_code,response_body,expected_result",
        [
            (200, {"received": True}, {"received": True}),
            (201, {"created": True}, {"created": True}),
            (202, {"accepted": True}, {"accepted": True}),
            (204, None, {}),
            (299, {"edge_case": True}, {"edge_case": True}),
        ],
    )
    def test_execute_webhook_event_handles_successful_status_codes(
        self, status_code, response_body, expected_result
    ):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        if response_body is None:
            responses.add(responses.POST, webhook.url, status=status_code)
        else:
            responses.add(
                responses.POST, webhook.url, json=response_body, status=status_code
            )

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == expected_result
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS
        assert event.response_status_code == status_code

    @responses.activate
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422, 499])
    def test_execute_webhook_event_handles_client_error_responses(self, status_code):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(
            responses.POST,
            webhook.url,
            json={"error": "Client error"},
            status=status_code,
        )

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {"error": "Client error"}
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert event.response_status_code == status_code
        assert (
            f"Webhook event {event.id} failed with HTTP {status_code}"
            in event.error_message
        )

    @responses.activate
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504, 599])
    def test_execute_webhook_event_handles_server_error_responses(self, status_code):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(
            responses.POST,
            webhook.url,
            body="Internal Server Error",
            status=status_code,
        )

        result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert event.response_status_code == status_code
        assert (
            f"Webhook event {event.id} failed with HTTP {status_code}"
            in event.error_message
        )

    @responses.activate
    def test_execute_webhook_event_marks_exhausted_when_client_error_and_max_retries_reached(
        self,
    ):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=3)

        responses.add(responses.POST, webhook.url, status=404)

        WebhookExecutionService().execute_webhook_event(event)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.EXHAUSTED

    def test_execute_webhook_event_handles_timeout_exception(self):
        webhook = WebhookFactory(timeout_seconds=30, max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout()

            result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert "Request timeout after 30 seconds" in event.error_message

    def test_execute_webhook_event_handles_connection_error(self):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError(
                "Connection refused"
            )

            result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert "Request error: Connection refused" in event.error_message

    def test_execute_webhook_event_handles_generic_request_exception(self):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException(
                "Generic request error"
            )

            result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert "Request error: Generic request error" in event.error_message

    @responses.activate
    def test_execute_webhook_event_handles_invalid_json_response(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, body="invalid json", status=200)

        with patch("webhooks.services.logger") as mock_logger:
            result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        mock_logger.exception.assert_called_once()
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS

    @responses.activate
    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_successful_delivery(self, mock_logger):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        WebhookExecutionService().execute_webhook_event(event)

        mock_logger.info.assert_called_once_with(
            "Webhook event %s delivered successfully to %s",
            event.id,
            webhook.url,
        )

    @responses.activate
    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_client_error_warning(self, mock_logger):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, status=400)

        WebhookExecutionService().execute_webhook_event(event)

        mock_logger.warning.assert_called_once_with(
            f"Webhook event {event.id} failed with HTTP 400",
            extra={"response_content": b""},
        )

    @responses.activate
    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_server_error_warning(self, mock_logger):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, status=500)

        WebhookExecutionService().execute_webhook_event(event)

        mock_logger.warning.assert_called_once_with(
            f"Webhook event {event.id} failed with HTTP 500",
            extra={"response_content": b""},
        )

    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_timeout_warning(self, mock_logger):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout()

            WebhookExecutionService().execute_webhook_event(event)

        mock_logger.warning.assert_called_once_with(
            f"Webhook event {event.id} timed out"
        )

    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_request_error_with_exception(self, mock_logger):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException(
                "Network error"
            )

            WebhookExecutionService().execute_webhook_event(event)

        mock_logger.error.assert_called_once_with(
            f"Webhook event {event.id} request failed", exc_info=True
        )

    def test_get_response_handles_json_response_successfully(self):
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.status_code = 200

        result = WebhookExecutionService._get_response(mock_response, 123)

        assert result == {"success": True}

    def test_get_response_handles_json_parsing_error(self):
        mock_response = Mock()
        mock_response.json.side_effect = Exception("Invalid JSON")
        mock_response.status_code = 200

        with patch("webhooks.services.logger") as mock_logger:
            result = WebhookExecutionService._get_response(mock_response, 123)

        assert result == {}
        mock_logger.exception.assert_called_once_with(
            "Failed to parse webhook response for event 123 for status 200",
            extra={"response_content": mock_response.content},
        )

    @pytest.mark.parametrize(
        "json_error",
        [
            ValueError("Invalid JSON"),
            TypeError("Type error"),
            UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte"),
        ],
    )
    def test_get_response_handles_different_json_exceptions(self, json_error):
        mock_response = Mock()
        mock_response.json.side_effect = json_error
        mock_response.status_code = 200

        result = WebhookExecutionService._get_response(mock_response, 456)

        assert result == {}

    @responses.activate
    def test_retry_failed_events_processes_all_failed_events_that_can_retry(self):
        webhook = WebhookFactory()
        failed_event1 = WebhookEventFailedFactory(webhook=webhook)
        failed_event2 = WebhookEventFailedFactory(webhook=webhook)
        WebhookEventExhaustedFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 2
        assert len(responses.calls) == 2

        failed_event1.refresh_from_db()
        failed_event2.refresh_from_db()
        assert failed_event1.status == WebhookEventStatus.SUCCESS
        assert failed_event2.status == WebhookEventStatus.SUCCESS

    @responses.activate
    def test_retry_failed_events_filters_by_webhook_id_when_provided(self):
        webhook1 = WebhookFactory()
        webhook2 = WebhookFactory()
        failed_event1 = WebhookEventFailedFactory(webhook=webhook1)
        failed_event2 = WebhookEventFailedFactory(webhook=webhook2)

        responses.add(responses.POST, webhook1.url, json={"received": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events(
            webhook_id=webhook1.id
        )

        assert processed_count == 1
        assert len(responses.calls) == 1

        failed_event1.refresh_from_db()
        failed_event2.refresh_from_db()
        assert failed_event1.status == WebhookEventStatus.SUCCESS
        assert failed_event2.status == WebhookEventStatus.FAILED

    def test_retry_failed_events_skips_events_that_cannot_retry(self):
        WebhookEventExhaustedFactory()

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 0

    @responses.activate
    def test_retry_failed_events_continues_processing_despite_individual_failures(self):
        webhook = WebhookFactory()
        failed_event1 = WebhookEventFailedFactory(webhook=webhook)
        failed_event2 = WebhookEventFailedFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, status=500, body="Server Error")
        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 2
        assert len(responses.calls) == 2

        failed_event1.refresh_from_db()
        failed_event2.refresh_from_db()
        statuses = {failed_event1.status, failed_event2.status}
        assert WebhookEventStatus.SUCCESS in statuses
        assert WebhookEventStatus.FAILED in statuses

    def test_retry_failed_events_returns_zero_when_no_failed_events_exist(self):
        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 0

    def test_retry_failed_events_skips_pending_events(self):
        WebhookEventFactory()

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 0

    def test_retry_failed_events_skips_successful_events(self):
        WebhookEventSuccessFactory()

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 0

    @responses.activate
    def test_retry_failed_events_handles_mixed_webhook_types(self):
        webhook1 = WebhookFactory()
        webhook2 = WebhookFactory()
        _ = WebhookEventFailedFactory(webhook=webhook1)
        _ = WebhookEventFailedFactory(webhook=webhook2)

        responses.add(responses.POST, webhook1.url, json={"success": True}, status=200)
        responses.add(responses.POST, webhook2.url, json={"success": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 2

    @responses.activate
    def test_retry_failed_events_respects_webhook_id_filter_with_no_matches(self):
        webhook1 = WebhookFactory()
        webhook2 = WebhookFactory()
        WebhookEventFailedFactory(webhook=webhook1)

        processed_count = WebhookExecutionService().retry_failed_events(
            webhook_id=webhook2.id
        )

        assert processed_count == 0

    @responses.activate
    def test_execute_webhook_event_uses_correct_request_parameters(self):
        webhook = WebhookFactory(timeout_seconds=45)
        event = WebhookEventFactory(
            webhook=webhook, payload={"test": "data", "nested": {"key": "value"}}
        )

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            WebhookExecutionService().execute_webhook_event(event)

            mock_post.assert_called_once_with(
                webhook.url,
                json={"test": "data", "nested": {"key": "value"}},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=45,
                allow_redirects=False,
            )

    @responses.activate
    def test_execute_webhook_event_does_not_follow_redirects(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            WebhookExecutionService().execute_webhook_event(event)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["allow_redirects"] is False

    @responses.activate
    def test_execute_webhook_event_sets_last_attempted_at_timestamp(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        with time_machine.travel("2024-01-15 14:30:00"):
            WebhookExecutionService().execute_webhook_event(event)

        event.refresh_from_db()
        expected_time = timezone.datetime(
            2024, 1, 15, 14, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert abs((event.last_attempted_at - expected_time).total_seconds()) < 1

    @responses.activate
    def test_execute_webhook_event_combines_auth_headers_with_default_headers(self):
        webhook_auth = WebhookAuthBearerFactory(api_key="secret-token")
        webhook = WebhookWithAuthFactory(auth=webhook_auth)
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        WebhookExecutionService().execute_webhook_event(event)

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Authorization"] == "Bearer secret-token"

    def test_execute_webhook_event_handles_webhook_with_expired_auth(self):
        expired_auth = WebhookAuthBearerFactory(expired=True)
        webhook = WebhookWithAuthFactory(auth=expired_auth)
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            WebhookExecutionService().execute_webhook_event(event)

            call_kwargs = mock_post.call_args[1]
            headers = call_kwargs["headers"]
            assert "Authorization" not in headers
            assert headers["Content-Type"] == "application/json"
            assert headers["Accept"] == "application/json"

    @responses.activate
    @pytest.mark.parametrize("custom_timeout", [1, 15, 60, 120, 180])
    def test_execute_webhook_event_respects_webhook_timeout_settings(
        self, custom_timeout
    ):
        webhook = WebhookFactory(timeout_seconds=custom_timeout)
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            WebhookExecutionService().execute_webhook_event(event)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["timeout"] == custom_timeout

    @responses.activate
    def test_execute_webhook_event_handles_empty_response_body(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, body="", status=200)

        with patch("webhooks.services.logger") as mock_logger:
            result = WebhookExecutionService().execute_webhook_event(event)

        assert result == {}
        mock_logger.exception.assert_called_once()
        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS

    @patch("webhooks.services.logger")
    def test_execute_webhook_event_logs_completed_event_warning(self, mock_logger):
        completed_event = WebhookEventSuccessFactory()

        with pytest.raises(WebHookExecutionError):
            WebhookExecutionService().execute_webhook_event(completed_event)

        mock_logger.warning.assert_called_once_with(
            f"Attempted to execute completed event {completed_event.id}"
        )

    @responses.activate
    def test_execute_webhook_event_preserves_existing_attempt_count_on_success(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook, attempt_count=2)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        WebhookExecutionService().execute_webhook_event(event)

        event.refresh_from_db()
        assert event.attempt_count == 3

    @responses.activate
    def test_execute_webhook_event_preserves_existing_attempt_count_on_failure(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(responses.POST, webhook.url, status=500)

        WebhookExecutionService().execute_webhook_event(event)

        event.refresh_from_db()
        assert event.attempt_count == 2

    @responses.activate
    def test_retry_failed_events_processes_events_in_database_order(self):
        webhook = WebhookFactory()

        with time_machine.travel("2024-01-15 10:00:00"):
            _ = WebhookEventFailedFactory(webhook=webhook)

        with time_machine.travel("2024-01-15 09:00:00"):
            _ = WebhookEventFailedFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 2
        assert len(responses.calls) == 2

    @responses.activate
    def test_retry_failed_events_handles_execution_exceptions_gracefully(self):
        webhook = WebhookFactory()
        _ = WebhookEventFailedFactory(webhook=webhook)
        _ = WebhookEventFailedFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, status=500, body="Server Error")
        responses.add(responses.POST, webhook.url, json={"success": True}, status=200)

        processed_count = WebhookExecutionService().retry_failed_events()

        assert processed_count == 2

    @responses.activate
    def test_send_webhook_returns_response_data_on_success(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)
        expected_response = {"transaction_id": "TXN_123", "status": "processed"}

        responses.add(responses.POST, webhook.url, json=expected_response, status=200)

        result = WebhookExecutionService()._send_webhook(webhook, event)

        assert result == expected_response

    def test_send_webhook_returns_empty_dict_on_timeout(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout()

            result = WebhookExecutionService()._send_webhook(webhook, event)

        assert result == {}

    def test_send_webhook_returns_empty_dict_on_request_exception(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException(
                "Network error"
            )

            result = WebhookExecutionService()._send_webhook(webhook, event)

        assert result == {}

    @responses.activate
    def test_send_webhook_returns_response_data_on_client_error(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)
        error_response = {"error": "Invalid payload", "code": "VALIDATION_ERROR"}

        responses.add(responses.POST, webhook.url, json=error_response, status=400)

        result = WebhookExecutionService()._send_webhook(webhook, event)

        assert result == error_response

    @responses.activate
    def test_send_webhook_returns_empty_dict_on_server_error(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)

        responses.add(
            responses.POST, webhook.url, body="Internal Server Error", status=500
        )

        result = WebhookExecutionService()._send_webhook(webhook, event)

        assert result == {}
