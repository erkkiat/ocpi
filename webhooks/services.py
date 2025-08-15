from django.core.exceptions import ValidationError
from django.conf import settings

from webhooks.models import Webhook


class WebhookValidationService:
    MAX_ACTIVE_WEBHOOKS_PER_TYPE = getattr(settings, "WEBHOOK_MAX_ACTIVE_PER_TYPE", 5)

    @classmethod
    def validate_webhook_activation_limits(cls, webhook: Webhook) -> None:
        if not webhook.active:
            return

        other_active_count = (
            Webhook.objects.filter(type=webhook.type, active=True)
            .exclude(pk=webhook.pk)
            .count()
        )

        if other_active_count >= cls.MAX_ACTIVE_WEBHOOKS_PER_TYPE:
            raise ValidationError(
                {
                    "active": f"Cannot activate webhook. Maximum {cls.MAX_ACTIVE_WEBHOOKS_PER_TYPE} "
                    f"active webhooks allowed per type. Currently have {other_active_count} "
                    f"other active webhooks of type {webhook.get_type_display()}."
                }
            )

    @classmethod
    def validate_webhook_before_save(cls, webhook: Webhook) -> None:
        webhook.full_clean()
        cls.validate_webhook_activation_limits(webhook)


class WebhookService:
    """Service for webhook business operations"""

    validation_service = WebhookValidationService()

    @classmethod
    def create_webhook(cls, **webhook_data) -> Webhook:
        webhook = Webhook(**webhook_data)
        cls.validation_service.validate_webhook_before_save(webhook)
        webhook.save()
        return webhook

    @classmethod
    def activate_webhook(cls, webhook: Webhook) -> Webhook:
        webhook.active = True
        cls.validation_service.validate_webhook_before_save(webhook)
        webhook.save()
        return webhook

    @classmethod
    def deactivate_webhook(cls, webhook: Webhook) -> Webhook:
        webhook.active = False
        webhook.save()
        return webhook

    @classmethod
    def update_webhook(cls, webhook: Webhook, **update_data) -> Webhook:
        # Apply updates
        for field, value in update_data.items():
            setattr(webhook, field, value)

        # Validate before saving
        cls.validation_service.validate_webhook_before_save(webhook)
        webhook.save()
        return webhook

    @classmethod
    def get_active_webhooks_by_type(cls, webhook_type: str) -> list[Webhook]:
        return list(Webhook.objects.filter(type=webhook_type, active=True))

    @classmethod
    def get_webhook_counts_by_type(cls) -> dict[str, dict[str, int]]:
        from collections import defaultdict
        from webhooks.choices import WebhookType

        counts = defaultdict(lambda: {"active": 0, "inactive": 0, "total": 0})

        for webhook_type, _ in WebhookType.choices:
            active_count = Webhook.objects.filter(
                type=webhook_type, active=True
            ).count()
            inactive_count = Webhook.objects.filter(
                type=webhook_type, active=False
            ).count()
            total_count = active_count + inactive_count

            counts[webhook_type] = {
                "active": active_count,
                "inactive": inactive_count,
                "total": total_count,
            }

        return dict(counts)
