import factory
from django.utils import timezone

from webhooks.models import (
    WebhookAuth,
    Webhook,
    WebhookEvent,
    WebhookAuthType,
    WebhookEventStatus,
)
from webhooks.choices import WebhookType, RemoteCommandType


class WebhookAuthFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WebhookAuth

    name = factory.Sequence(lambda n: f"Auth Config {n}")
    auth_type = WebhookAuthType.NONE
    expired = False


class WebhookAuthBearerFactory(WebhookAuthFactory):
    auth_type = WebhookAuthType.BEARER
    api_key = "test-api-key-123"


class WebhookAuthBasicFactory(WebhookAuthFactory):
    auth_type = WebhookAuthType.BASIC
    username = "testuser"
    password = "testpass"


class WebhookAuthApiKeyFactory(WebhookAuthFactory):
    auth_type = WebhookAuthType.API_KEY
    api_key = "test-api-key-456"
    api_key_header = "X-API-Key"


class WebhookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Webhook

    type = WebhookType.CHARGEPOINT_STATUS
    command_type = RemoteCommandType.START_SESSION
    url = factory.Sequence(lambda n: f"https://example.com/webhook/{n}")
    max_retries = 3
    timeout_seconds = 30
    active = True


class WebhookWithAuthFactory(WebhookFactory):
    auth = factory.SubFactory(WebhookAuthBearerFactory)


class WebhookInactiveFactory(WebhookFactory):
    active = False


class WebhookRemoteCommandFactory(WebhookFactory):
    type = WebhookType.REMOTE_COMMAND
    command_type = RemoteCommandType.START_SESSION


class WebhookFACFactory(WebhookFactory):
    type = WebhookType.FINANCIAL_ADVICE_CONFIRMATION
    command_type = None


class WebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WebhookEvent

    webhook = factory.SubFactory(WebhookFactory)
    event_type = "charge_point.status_changed"
    payload = {"charge_point_id": "CP_001", "status": "Available"}
    status = WebhookEventStatus.PENDING
    attempt_count = 0


class WebhookEventSuccessFactory(WebhookEventFactory):
    status = WebhookEventStatus.SUCCESS
    attempt_count = 1
    completed_at = factory.LazyFunction(timezone.now)
    response_status_code = 200


class WebhookEventFailedFactory(WebhookEventFactory):
    status = WebhookEventStatus.FAILED
    attempt_count = 1
    last_attempted_at = factory.LazyFunction(timezone.now)
    error_message = "Connection timeout"
    response_status_code = 500

    @factory.lazy_attribute
    def webhook(self):
        return WebhookFactory(max_retries=3)


class WebhookEventExhaustedFactory(WebhookEventFactory):
    status = WebhookEventStatus.EXHAUSTED
    attempt_count = 3
    last_attempted_at = factory.LazyFunction(timezone.now)
    completed_at = factory.LazyFunction(timezone.now)
    error_message = "Maximum retries exceeded"
    response_status_code = 500
