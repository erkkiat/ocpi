import logging

from celery import shared_task

from webhooks.models import WebhookEvent
from webhooks.services import WebhookExecutionService

logger = logging.getLogger(__name__)


@shared_task
def execute_webhook_event(event_id: int) -> None:
    try:
        event = WebhookEvent.objects.get(id=event_id)
    except WebhookEvent.DoesNotExist:
        logger.error("WebhookEvent with id %s does not exist", event_id)
        return

    WebhookExecutionService().execute_webhook_event(event)
