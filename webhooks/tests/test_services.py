import pytest
from unittest.mock import patch
from django.utils import timezone
import time_machine
import requests
import responses
from django.core.exceptions import ValidationError

from webhooks.services import (
    WebhookService,
    WebhookEventService,
    WebhookExecutionService,
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


@pytest.mark.django_db
class TestWebhookEventService:
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

    def test_create_event_raises_on_invalid_event_type(self):
        webhook = WebhookFactory()
        custom_event_type = "custom.event.type"
        payload = {"data": "test"}

        with pytest.raises(
            ValidationError, match=f"Invalid event type: {custom_event_type}"
        ):
            WebhookEventService.create_event(webhook, custom_event_type, payload)

    def test_get_pending_events_returns_only_pending_events_for_webhook(self):
        webhook = WebhookFactory()
        pending_event = WebhookEventFactory(webhook=webhook)
        WebhookEventFailedFactory(webhook=webhook)
        WebhookEventSuccessFactory(webhook=webhook)

        pending_events = WebhookEventService.get_pending_events(webhook)

        assert pending_events.count() == 1
        assert pending_events.first().id == pending_event.id
        assert pending_events.first().status == WebhookEventStatus.PENDING

    def test_mark_attempt_started_increments_attempt_count_and_sets_timestamp(self):
        webhook_event = WebhookEventFactory()

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_attempt_started(webhook_event)

        webhook_event.refresh_from_db()
        assert webhook_event.attempt_count == 1
        # Check that the timestamp is close to the expected time (within 1 second)
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert (
            abs((webhook_event.last_attempted_at - expected_time).total_seconds()) < 1
        )

    def test_mark_success_sets_success_status_and_completion_data(self):
        webhook_event = WebhookEventFactory()

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_success(webhook_event, status_code=201)

        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.SUCCESS
        # Check that the timestamp is close to the expected time (within 1 second)
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert abs((webhook_event.completed_at - expected_time).total_seconds()) < 1
        assert webhook_event.response_status_code == 201
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
        event = WebhookEventFactory(webhook=webhook, attempt_count=3)
        error_message = "Maximum retries exceeded"

        with time_machine.travel("2024-01-15 10:30:00"):
            WebhookEventService.mark_failed(event, error_message)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.EXHAUSTED
        assert event.error_message == error_message
        # Check that the timestamp is close to the expected time (within 1 second)
        expected_time = timezone.datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.timezone.utc
        )
        assert abs((event.completed_at - expected_time).total_seconds()) < 1


@pytest.mark.django_db
class TestWebhookExecutionService:
    def test_trigger_webhook_by_id_creates_event_for_active_webhook(self):
        webhook = WebhookFactory()
        event_type = WebhookEventType.SESSION_STARTED
        payload = {"session_id": "SES_001"}

        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, webhook.url, json={"success": True}, status=200)

            event = WebhookExecutionService.trigger_webhook_by_id(
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

        result = WebhookExecutionService.trigger_webhook_by_id(
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

        result = WebhookExecutionService.trigger_webhook_by_id(
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

            result = WebhookExecutionService.trigger_webhook_by_id(
                webhook.id, WebhookEventType.SESSION_STARTED, {"test": "data"}
            )

        assert result is None
        mock_logger.error.assert_called_once_with(
            f"Failed to create/execute webhook event for webhook ID {webhook.id}",
            exc_info=True,
        )

    def test_execute_webhook_event_returns_true_when_event_already_completed(self):
        webhook_event = WebhookEventSuccessFactory()

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is True

    def test_execute_webhook_event_returns_false_when_webhook_inactive(self):
        inactive_webhook = WebhookInactiveFactory()
        webhook_event = WebhookEventFactory(webhook=inactive_webhook, attempt_count=1)

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is False
        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert webhook_event.error_message == "Webhook is not active"

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

        result = WebhookExecutionService.execute_webhook_event(event)

        assert result is True
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

        result = WebhookExecutionService.execute_webhook_event(event)

        assert result is True
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        expected_auth_header = (
            "Basic dGVzdHVzZXI6dGVzdHBhc3M="  # base64 of testuser:testpass
        )
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

        result = WebhookExecutionService.execute_webhook_event(event)

        assert result is True
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

        result = WebhookExecutionService.execute_webhook_event(event)

        assert result is True
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert "Authorization" not in request.headers

    @responses.activate
    def test_execute_webhook_event_handles_http_error_response(self):
        webhook = WebhookFactory(max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(
            responses.POST,
            webhook_event.webhook.url,
            body="Internal Server Error",
            status=500,
        )

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is False
        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert webhook_event.response_status_code == 500
        assert "HTTP 500: Internal Server Error" in webhook_event.error_message

    @responses.activate
    def test_execute_webhook_event_handles_timeout_exception(self):
        webhook = WebhookFactory(timeout_seconds=30, max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(responses.POST, webhook.url, body=requests.exceptions.Timeout())

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is False
        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert "Request timeout after 30 seconds" in webhook_event.error_message

    @responses.activate
    def test_execute_webhook_event_handles_connection_error(self):
        webhook = WebhookFactory(max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(
            responses.POST,
            webhook_event.webhook.url,
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is False
        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert "Request error: Connection refused" in webhook_event.error_message

    @responses.activate
    def test_execute_webhook_event_handles_request_exception(self):
        webhook = WebhookFactory(max_retries=3)
        webhook_event = WebhookEventFactory(webhook=webhook, attempt_count=1)

        responses.add(
            responses.POST,
            webhook_event.webhook.url,
            body=requests.exceptions.RequestException("Generic request error"),
        )

        result = WebhookExecutionService.execute_webhook_event(webhook_event)

        assert result is False
        webhook_event.refresh_from_db()
        assert webhook_event.status == WebhookEventStatus.FAILED
        assert "Request error: Generic request error" in webhook_event.error_message

    @responses.activate
    def test_retry_failed_events_processes_all_failed_events_that_can_retry(self):
        webhook = WebhookFactory()
        failed_event1 = WebhookEventFailedFactory(webhook=webhook)
        failed_event2 = WebhookEventFailedFactory(webhook=webhook)
        WebhookEventExhaustedFactory(webhook=webhook)  # Should be skipped

        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        processed_count = WebhookExecutionService.retry_failed_events()

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

        processed_count = WebhookExecutionService.retry_failed_events(
            webhook_id=webhook1.id
        )

        assert processed_count == 1
        assert len(responses.calls) == 1

        failed_event1.refresh_from_db()
        failed_event2.refresh_from_db()
        assert failed_event1.status == WebhookEventStatus.SUCCESS
        assert failed_event2.status == WebhookEventStatus.FAILED  # Should remain failed

    def test_retry_failed_events_skips_events_that_cannot_retry(self):
        WebhookEventExhaustedFactory()

        processed_count = WebhookExecutionService.retry_failed_events()

        assert processed_count == 0

    @responses.activate
    def test_retry_failed_events_processes_all_events_despite_individual_failures(self):
        webhook = WebhookFactory()
        failed_event1 = WebhookEventFailedFactory(webhook=webhook)
        failed_event2 = WebhookEventFailedFactory(webhook=webhook)

        responses.add(responses.POST, webhook.url, status=500, body="Server Error")
        responses.add(responses.POST, webhook.url, json={"received": True}, status=200)

        processed_count = WebhookExecutionService.retry_failed_events()

        assert processed_count == 2
        assert len(responses.calls) == 2

        failed_event1.refresh_from_db()
        failed_event2.refresh_from_db()
        statuses = {failed_event1.status, failed_event2.status}
        assert WebhookEventStatus.SUCCESS in statuses
        assert WebhookEventStatus.FAILED in statuses
