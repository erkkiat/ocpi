from django_cryptography.fields import encrypt
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MaxValueValidator, MinValueValidator
from django.conf import settings
import base64
import re

from webhooks.choices import WebhookType, RemoteCommandType


class WebhookAuthType(models.TextChoices):
    NONE = "none", "No Authentication"
    BASIC = "basic", "Basic Authentication"
    BEARER = "bearer", "Bearer Token"
    API_KEY = "api_key", "API Key"


api_key_header_validator = RegexValidator(
    regex=r"^[A-Za-z][A-Za-z0-9\-_]*$",
    message="Header name must start with a letter and contain only letters, numbers, hyphens, and underscores",
)


class WebhookAuthValidator:
    @staticmethod
    def validate_required_fields(
        auth_type: str, username: str, password: str, api_key: str, api_key_header: str
    ) -> None:
        errors = {}

        if auth_type == WebhookAuthType.BASIC:
            if not username or not password:
                errors["auth_type"] = (
                    "Username and password are required for basic authentication"
                )

        elif auth_type == WebhookAuthType.BEARER:
            if not api_key:
                errors["api_key"] = (
                    "API key is required for bearer token authentication"
                )

        elif auth_type == WebhookAuthType.API_KEY:
            if not api_key:
                errors["api_key"] = "API key is required for API key authentication"
            if not api_key_header:
                errors["api_key_header"] = (
                    "Header name is required for API key authentication"
                )

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def validate_api_key_header_format(api_key_header: str) -> None:
        if api_key_header and api_key_header != "X-API-Key":
            if not re.match(r"^[A-Za-z][A-Za-z0-9\-_]*$", api_key_header):
                raise ValidationError(
                    {
                        "api_key_header": "Invalid header name format. Must start with a letter and contain only letters, numbers, hyphens, and underscores."
                    }
                )

    @classmethod
    def validate_auth_configuration(
        cls,
        auth_type: str,
        username: str,
        password: str,
        api_key: str,
        api_key_header: str,
    ) -> None:
        cls.validate_required_fields(
            auth_type, username, password, api_key, api_key_header
        )
        cls.validate_api_key_header_format(api_key_header)


class WebhookValidator:
    MAX_ACTIVE_WEBHOOKS_PER_TYPE = getattr(settings, "WEBHOOK_MAX_ACTIVE_PER_TYPE", 5)

    @staticmethod
    def validate_remote_command_requirements(
        webhook_type: str, command_type: str
    ) -> None:
        if webhook_type == WebhookType.REMOTE_COMMAND and not command_type:
            raise ValidationError(
                {"command_type": "Command type is required for remote command webhooks"}
            )

    @staticmethod
    def validate_auth_not_expired(auth) -> None:
        if auth and auth.expired:
            raise ValidationError(
                {"auth": "Cannot use expired authentication configuration"}
            )

    @classmethod
    def validate_webhook_configuration(
        cls, webhook_type: str, command_type: str, auth
    ) -> None:
        cls.validate_remote_command_requirements(webhook_type, command_type)

    @classmethod
    def validate_webhook_activation_limits(cls, webhook) -> None:
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


class WebhookAuth(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Descriptive name for this auth config (e.g., 'Production API', 'Staging Basic')",
    )
    auth_type = models.CharField(
        max_length=10,
        choices=WebhookAuthType.choices,
        default=WebhookAuthType.NONE,
    )

    username = encrypt(
        models.CharField(
            max_length=255,
            blank=True,
            null=True,
            help_text="Username for basic authentication",
        )
    )
    password = encrypt(
        models.CharField(
            max_length=255,
            blank=True,
            null=True,
            help_text="Password for basic authentication",
        )
    )
    api_key = encrypt(
        models.TextField(
            blank=True,
            null=True,
            help_text="API key for bearer token or API key authentication",
        )
    )

    api_key_header = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default="X-API-Key",
        validators=[api_key_header_validator],
        help_text="Header name for API key authentication (e.g., 'X-API-Key', 'Authorization')",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expired = models.BooleanField(
        default=False,
        help_text="Mark as expired to disable this authentication configuration",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    ~models.Q(auth_type=WebhookAuthType.API_KEY)
                    | (
                        models.Q(auth_type=WebhookAuthType.API_KEY)
                        & ~models.Q(api_key_header__isnull=True)
                        & ~models.Q(api_key_header="")
                    )
                ),
                name="api_key_auth_requires_header",
            ),
        ]

    def clean(self):
        super().clean()

        WebhookAuthValidator.validate_auth_configuration(
            auth_type=self.auth_type,
            username=self.username,
            password=self.password,
            api_key=self.api_key,
            api_key_header=self.api_key_header,
        )

    def get_auth_headers(self):
        headers = {}

        if self.auth_type == WebhookAuthType.BASIC and self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"

        elif self.auth_type == WebhookAuthType.BEARER and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        elif (
            self.auth_type == WebhookAuthType.API_KEY
            and self.api_key
            and self.api_key_header
        ):
            headers[self.api_key_header] = self.api_key

        return headers

    def is_valid_auth(self):
        return not self.expired and bool(self.get_auth_headers())

    def __str__(self):
        return f"{self.name} ({self.get_auth_type_display()})"


class Webhook(models.Model):
    type = models.CharField(
        max_length=25,
        choices=WebhookType.choices,
    )
    command_type = models.CharField(
        max_length=25,
        choices=RemoteCommandType.choices,
        blank=True,
        null=True,
        verbose_name="Remote Command Type",
        help_text="Required only for Remote Command webhooks",
    )
    url = models.URLField(help_text="Full URL where webhook notifications will be sent")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auth = models.ForeignKey(
        WebhookAuth,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text="Authentication configuration for this webhook",
    )
    max_retries = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Maximum number of retry attempts for failed webhook calls (0-10)",
    )
    timeout_seconds = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(180)],
        help_text="Timeout in seconds for webhook HTTP requests",
    )
    active = models.BooleanField(
        default=False,
        help_text="Whether this webhook is active and should receive notifications",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    ~models.Q(type=WebhookType.REMOTE_COMMAND)
                    | (
                        models.Q(type=WebhookType.REMOTE_COMMAND)
                        & ~models.Q(command_type__isnull=True)
                    )
                ),
                name="remote_command_requires_command_type",
            ),
            models.UniqueConstraint(
                fields=["url"],
                condition=models.Q(active=True),
                name="unique_active_webhook_url",
            ),
        ]

    def clean(self):
        super().clean()

        WebhookValidator.validate_webhook_configuration(
            webhook_type=self.type, command_type=self.command_type, auth=self.auth
        )
        WebhookValidator.validate_webhook_activation_limits(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_auth_headers(self):
        if not self.auth or self.auth.expired:
            return {}
        return self.auth.get_auth_headers()

    def has_valid_auth(self):
        return self.auth and self.auth.is_valid_auth()

    def __str__(self):
        return f"{self.get_type_display()} - {self.url}"


class WebhookEventStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    EXHAUSTED = "exhausted", "Retries Exhausted"


class WebhookEventType:
    CHARGE_POINT_STATUS_CHANGED = "charge_point.status_changed"
    CHARGE_POINT_CREATED = "charge_point.created"
    CHARGE_POINT_UPDATED = "charge_point.updated"
    SESSION_STARTED = "session.started"
    SESSION_STOPPED = "session.stopped"
    SESSION_AUTHORIZED = "session.authorized"
    TOKEN_AUTHORIZED = "token.authorized"
    TOKEN_BLOCKED = "token.blocked"
    REMOTE_START_REQUESTED = "remote_command.start_requested"
    REMOTE_STOP_REQUESTED = "remote_command.stop_requested"
    INVOICE_GENERATED = "invoice.generated"
    INVOICE_SENT = "invoice.sent"

    @classmethod
    def get_all_standard_types(cls):
        return [
            getattr(cls, attr)
            for attr in dir(cls)
            if not attr.startswith("_") and isinstance(getattr(cls, attr), str)
        ]

    @classmethod
    def is_standard_type(cls, event_type):
        return event_type in cls.get_all_standard_types()


class WebhookEvent(models.Model):
    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        related_name="events",
        help_text="The webhook configuration that triggered this event",
    )

    event_type = models.CharField(
        max_length=100,
        help_text="Type of event (e.g., 'charge_point.status_changed'). Use WebhookEventType constants for standard events.",
    )

    payload = models.JSONField(help_text="The JSON payload sent to the webhook URL")

    status = models.CharField(
        max_length=20,
        choices=WebhookEventStatus.choices,
        default=WebhookEventStatus.PENDING,
    )

    attempt_count = models.PositiveSmallIntegerField(
        default=0, help_text="Number of delivery attempts made"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    error_message = models.TextField(
        blank=True, help_text="Error message from the last failed attempt"
    )

    response_status_code = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="HTTP status code from the last attempt"
    )

    response_time_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Response time in milliseconds from the last attempt",
    )

    class Meta:
        db_table = "webhook_events"
        indexes = [
            models.Index(fields=["webhook", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["event_type"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"WebhookEvent {self.id} - {self.webhook.url} ({self.status})"

    @property
    def can_retry(self):
        return self.attempt_count < self.webhook.max_retries

    @property
    def is_completed(self):
        return self.status in [WebhookEventStatus.SUCCESS, WebhookEventStatus.EXHAUSTED]
