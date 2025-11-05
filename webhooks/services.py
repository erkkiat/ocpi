import requests
import logging

from django.core.exceptions import ValidationError
from requests import Response

from webhooks.models import Webhook, WebhookEvent, WebhookEventStatus, WebhookEventType
from django.utils import timezone

logger = logging.getLogger(__name__)


class WebhookService:
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


class WebhookEventService:
    @classmethod
    def create_event(cls, webhook: Webhook, event_type: str, payload: dict):
        if event_type not in WebhookEventType:
            raise ValidationError(f"Invalid event type: {event_type}")
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


class WebHookExecutionError(Exception):
    pass


class WebhookExecutionService:
    def trigger_webhook_by_id(self, webhook_id: int, event_type: str, payload: dict):
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

            self.execute_webhook_event(event)
            return event

        except Exception:
            logger.error(
                f"Failed to create/execute webhook event for webhook ID {webhook_id}",
                exc_info=True,
            )
            return None

    @staticmethod
    def _get_response(response: Response, webhook_event_id: int):
        try:
            return response.json()
        except Exception:
            logger.exception(
                f"Failed to parse webhook response for event {webhook_event_id} for status {response.status_code}",
                extra={"response_content": response.content},
            )
            return {}

    def execute_webhook_event(self, event: WebhookEvent):
        if event.is_completed:
            logger.warning(f"Attempted to execute completed event {event.id}")
            raise WebHookExecutionError("Cannot send to completed event")

        webhook = event.webhook
        if not webhook.active:
            WebhookEventService.mark_failed(event, "Webhook is not active")
            logger.warning(
                f"Cannot send webhook request to inactive webhook {webhook.id} - {webhook.url}, "
            )
            raise WebHookExecutionError(
                f"Cannot send webhook request to a inactive webhook configuration id: {webhook.id} - url:{webhook.url}"
            )

        WebhookEventService.mark_attempt_started(event)
        response = self._send_webhook(webhook, event)
        return response

    def _send_webhook(self, webhook: Webhook, event: WebhookEvent):
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
                allow_redirects=False,
            )

            if 200 <= response.status_code < 300:
                WebhookEventService.mark_success(
                    event, status_code=response.status_code
                )
                logger.info(
                    "Webhook event %s delivered successfully to %s",
                    event.id,
                    webhook.url,
                )
                return self._get_response(response, event.id)
            elif 400 <= response.status_code < 500:
                error_msg = (
                    f"Webhook event {event.id} failed with HTTP {response.status_code}"
                )
                logger.warning(error_msg, extra={"response_content": response.content})
                WebhookEventService.mark_failed(
                    event, error_msg, status_code=response.status_code
                )
                return self._get_response(response, event.id)
            else:
                error_msg = (
                    f"Webhook event {event.id} failed with HTTP {response.status_code}"
                )
                WebhookEventService.mark_failed(
                    event, error_msg, status_code=response.status_code
                )
                logger.warning(error_msg, extra={"response_content": response.content})
                return {}
        except requests.exceptions.Timeout:
            error_msg = f"Request timeout after {webhook.timeout_seconds} seconds"
            WebhookEventService.mark_failed(event, error_msg)
            logger.warning(f"Webhook event {event.id} timed out")
            return {}

        except requests.exceptions.RequestException as e:
            WebhookEventService.mark_failed(event, f"Request error: {str(e)}")
            logger.error(f"Webhook event {event.id} request failed", exc_info=True)
            return {}

    def retry_failed_events(self, webhook_id=None):
        failed_events = WebhookEvent.objects.filter(status=WebhookEventStatus.FAILED)

        if webhook_id:
            failed_events = failed_events.filter(webhook_id=webhook_id)

        processed = 0
        for event in failed_events:
            if event.can_retry:
                self.execute_webhook_event(event)
                processed += 1

        return processed
