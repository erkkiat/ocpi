import logging

from celery import shared_task

from webhooks.models import WebhookEvent, WebhookEventStatus
from webhooks.services import WebhookExecutionService, WebHookExecutionError

logger = logging.getLogger(__name__)

RETRY_BACKOFF_BASE_SECONDS = 60


@shared_task(bind=True, max_retries=10)
def execute_webhook_event(self, event_id: int) -> None:
    try:
        event = WebhookEvent.objects.get(id=event_id)
    except WebhookEvent.DoesNotExist:
        logger.error("WebhookEvent with id %s does not exist", event_id)
        return

    try:
        WebhookExecutionService().execute_webhook_event(event)
    except WebHookExecutionError:
        return

    event.refresh_from_db()
    if event.status == WebhookEventStatus.FAILED:
        countdown = (2**event.attempt_count) * RETRY_BACKOFF_BASE_SECONDS
        raise self.retry(countdown=countdown)
