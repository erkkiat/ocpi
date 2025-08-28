from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.models import Webhook


class WebhookRepository:
    @staticmethod
    def get_remote_command_webhook(command_type: RemoteCommandType):
        return Webhook.objects.filter(
            type=WebhookType.REMOTE_COMMAND, command_type=command_type
        ).first()
