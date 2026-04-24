import pytest
import responses
from celery.exceptions import Retry

from webhooks.factories import WebhookFACFactory, WebhookEventFactory
from webhooks.models import Webhook, WebhookEventStatus, WebhookEventType
from webhooks.tasks import execute_webhook_event


@pytest.mark.django_db
class TestExecuteWebhookEventTask:
    @responses.activate
    def test_execute_webhook_event_marks_event_success_when_webhook_returns_200(self):
        webhook = WebhookFACFactory()
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.FAC_CREATED,
            payload={"terminal_id": "TERM-001"},
        )
        responses.add(responses.POST, webhook.url, json={}, status=200)

        execute_webhook_event(event.id)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.SUCCESS
        assert event.attempt_count == 1

    @responses.activate
    def test_execute_webhook_event_raises_retry_when_webhook_returns_500_and_retries_remain(
        self,
    ):
        webhook = WebhookFACFactory(max_retries=3)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.FAC_CREATED,
            payload={"terminal_id": "TERM-001"},
        )
        responses.add(responses.POST, webhook.url, json={}, status=500)

        with pytest.raises(Retry):
            execute_webhook_event(event.id)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert event.attempt_count == 1

    @responses.activate
    def test_execute_webhook_event_raises_retry_on_subsequent_failures(self):
        webhook = WebhookFACFactory(max_retries=10)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.FAC_CREATED,
            payload={"terminal_id": "TERM-001"},
            attempt_count=2,
        )
        responses.add(responses.POST, webhook.url, json={}, status=500)

        with pytest.raises(Retry):
            execute_webhook_event(event.id)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
        assert event.attempt_count == 3

    @responses.activate
    def test_execute_webhook_event_marks_event_exhausted_and_does_not_retry_when_no_retries_left(
        self,
    ):
        webhook = WebhookFACFactory(max_retries=0)
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.FAC_CREATED,
            payload={"terminal_id": "TERM-001"},
        )
        responses.add(responses.POST, webhook.url, json={}, status=500)

        execute_webhook_event(event.id)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.EXHAUSTED

    def test_execute_webhook_event_logs_error_when_event_does_not_exist(self, caplog):
        caplog.set_level("ERROR", logger="webhooks.tasks")

        execute_webhook_event(99999)

        assert "WebhookEvent with id 99999 does not exist" in caplog.text

    def test_execute_webhook_event_returns_without_retry_when_webhook_deactivated_between_creation_and_execution(
        self,
    ):
        webhook = WebhookFACFactory()
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.FAC_CREATED,
            payload={"terminal_id": "TERM-001"},
        )
        Webhook.objects.filter(pk=webhook.pk).update(active=False)

        execute_webhook_event(event.id)

        event.refresh_from_db()
        assert event.status == WebhookEventStatus.FAILED
