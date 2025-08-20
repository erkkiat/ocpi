import requests
import logging

from webhooks.models import Webhook, WebhookEvent, WebhookEventStatus, WebhookEventType
from django.utils import timezone

logger = logging.getLogger(__name__)


class WebhookService:
    @classmethod
    def create_webhook(cls, **webhook_data) -> Webhook:
        webhook = Webhook(**webhook_data)
        webhook.save()
        return webhook

    @classmethod
    def activate_webhook(cls, webhook: Webhook) -> Webhook:
        webhook.active = True
        webhook.save()
        return webhook

    @classmethod
    def deactivate_webhook(cls, webhook: Webhook) -> Webhook:
        webhook.active = False
        webhook.save()
        return webhook

    @classmethod
    def get_active_webhooks_by_type(cls, webhook_type: str) -> list[Webhook]:
        return list(Webhook.objects.filter(type=webhook_type, active=True))


class WebhookEventService:
    @classmethod
    def create_event(cls, webhook: Webhook, event_type: str, payload: dict):
        if not WebhookEventType.is_standard_type(event_type):
            logger.info(f"Cannot use custom event type: {event_type}")

        return WebhookEvent.objects.create(
            webhook=webhook, event_type=event_type, payload=payload
        )

    @classmethod
    def get_pending_events(cls, webhook: Webhook):
        return webhook.events.filter(status=WebhookEventStatus.PENDING)

    @classmethod
    def mark_attempt_started(cls, event: WebhookEvent):
        event.attempt_count += 1
        event.last_attempted_at = timezone.now()
        event.save(update_fields=["attempt_count", "last_attempted_at"])

    @classmethod
    def mark_success(cls, event: WebhookEvent, status_code=200):
        event.status = WebhookEventStatus.SUCCESS
        event.completed_at = timezone.now()
        event.response_status_code = status_code
        event.error_message = ""
        event.save(
            update_fields=[
                "status",
                "completed_at",
                "response_status_code",
                "error_message",
            ]
        )

    @classmethod
    def mark_failed(cls, event: WebhookEvent, error_message, status_code=None):
        event.error_message = error_message
        event.response_status_code = status_code

        if event.can_retry:
            event.status = WebhookEventStatus.FAILED
        else:
            event.status = WebhookEventStatus.EXHAUSTED
            event.completed_at = timezone.now()

        event.save(
            update_fields=[
                "status",
                "error_message",
                "response_status_code",
                "completed_at",
            ]
        )


class WebhookExecutionService:
    @classmethod
    def trigger_webhook_by_id(cls, webhook_id: int, event_type: str, payload: dict):
        try:
            webhook = Webhook.objects.get(id=webhook_id)
        except Webhook.DoesNotExist:
            logger.error(f"Webhook with ID {webhook_id} does not exist")
            return None

        if not webhook.active:
            logger.warning(
                f"Webhook with ID {webhook_id} is not active, skipping execution"
            )
            return None

        try:
            event = WebhookEventService.create_event(
                webhook=webhook, event_type=event_type, payload=payload
            )

            cls.execute_webhook_event(event)
            return event

        except Exception:
            logger.error(
                f"Failed to create/execute webhook event for webhook ID {webhook_id}",
                exc_info=True,
            )
            return None

    @classmethod
    def execute_webhook_event(cls, event: WebhookEvent):
        if event.is_completed:
            logger.warning(f"Attempted to execute completed event {event.id}")
            return event.status == WebhookEventStatus.SUCCESS

        webhook = event.webhook
        if not webhook.active:
            WebhookEventService.mark_failed(event, "Webhook is not active")
            return False

        WebhookEventService.mark_attempt_started(event)

        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                **webhook.get_auth_headers(),
            }

            response = requests.post(
                webhook.url,
                json=event.payload,
                headers=headers,
                timeout=webhook.timeout_seconds,
            )

            if response.status_code < 400:
                WebhookEventService.mark_success(
                    event, status_code=response.status_code
                )
                logger.info(
                    f"Webhook event {event.id} delivered successfully to {webhook.url}"
                )
                return True
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
                WebhookEventService.mark_failed(
                    event, error_msg, status_code=response.status_code
                )
                logger.warning(
                    f"Webhook event {event.id} failed with HTTP {response.status_code}"
                )
                return False

        except requests.exceptions.Timeout:
            error_msg = f"Request timeout after {webhook.timeout_seconds} seconds"
            WebhookEventService.mark_failed(event, error_msg)
            logger.warning(f"Webhook event {event.id} timed out")
            return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Request error: {str(e)}"
            WebhookEventService.mark_failed(event, error_msg)
            logger.error(f"Webhook event {event.id} request failed", exc_info=True)
            return False

    @classmethod
    def retry_failed_events(cls, webhook_id=None):
        failed_events = WebhookEvent.objects.filter(status=WebhookEventStatus.FAILED)

        if webhook_id:
            failed_events = failed_events.filter(webhook_id=webhook_id)

        processed = 0
        for event in failed_events:
            if event.can_retry:
                cls.execute_webhook_event(event)
                processed += 1

        return processed
