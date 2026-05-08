from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.models import Webhook


class WebhookRepository:
    @staticmethod
    def get_remote_command_webhook(command_type: RemoteCommandType) -> Webhook | None:
        return Webhook.objects.filter(
            type=WebhookType.REMOTE_COMMAND, command_type=command_type, active=True
        ).first()

    @staticmethod
    def get_fac_webhook() -> Webhook | None:
        return Webhook.objects.filter(
            type=WebhookType.FINANCIAL_ADVICE_CONFIRMATION, active=True
        ).first()

    @staticmethod
    def get_invoicing_webhook() -> Webhook | None:
        return Webhook.objects.filter(type=WebhookType.INVOICING, active=True).first()
