from django_cryptography.fields import encrypt
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MaxValueValidator, MinValueValidator
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
                    ~models.Q(auth_type=WebhookAuthType.BASIC)
                    | (
                        models.Q(auth_type=WebhookAuthType.BASIC)
                        & ~models.Q(username__isnull=True)
                        & ~models.Q(username="")
                        & ~models.Q(password__isnull=True)
                        & ~models.Q(password="")
                    )
                ),
                name="basic_auth_requires_username_and_password",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(
                        auth_type__in=[WebhookAuthType.BEARER, WebhookAuthType.API_KEY]
                    )
                    | (
                        models.Q(
                            auth_type__in=[
                                WebhookAuthType.BEARER,
                                WebhookAuthType.API_KEY,
                            ]
                        )
                        & ~models.Q(api_key__isnull=True)
                        & ~models.Q(api_key="")
                    )
                ),
                name="bearer_and_api_key_auth_require_api_key",
            ),
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
            models.CheckConstraint(
                check=(
                    ~models.Q(auth_type=WebhookAuthType.NONE)
                    | (
                        models.Q(auth_type=WebhookAuthType.NONE)
                        & (models.Q(username__isnull=True) | models.Q(username=""))
                        & (models.Q(password__isnull=True) | models.Q(password=""))
                        & (models.Q(api_key__isnull=True) | models.Q(api_key=""))
                    )
                ),
                name="none_auth_has_no_credentials",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(auth_type=WebhookAuthType.BASIC)
                    | (
                        models.Q(auth_type=WebhookAuthType.BASIC)
                        & (models.Q(api_key__isnull=True) | models.Q(api_key=""))
                    )
                ),
                name="basic_auth_has_no_api_key",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(
                        auth_type__in=[WebhookAuthType.BEARER, WebhookAuthType.API_KEY]
                    )
                    | (
                        models.Q(
                            auth_type__in=[
                                WebhookAuthType.BEARER,
                                WebhookAuthType.API_KEY,
                            ]
                        )
                        & (models.Q(username__isnull=True) | models.Q(username=""))
                        & (models.Q(password__isnull=True) | models.Q(password=""))
                    )
                ),
                name="token_auth_has_no_basic_credentials",
            ),
        ]

    def clean(self):
        super().clean()

        if self.auth_type == WebhookAuthType.BASIC:
            if not self.username or not self.password:
                raise ValidationError(
                    {
                        "auth_type": "Username and password are required for basic authentication"
                    }
                )
            if self.api_key:
                raise ValidationError(
                    {"api_key": "API key should not be set for basic authentication"}
                )

        elif self.auth_type == WebhookAuthType.BEARER:
            if not self.api_key:
                raise ValidationError(
                    {"api_key": "API key is required for bearer token authentication"}
                )
            if self.username or self.password:
                raise ValidationError(
                    {
                        "username": "Username and password should not be set for bearer authentication"
                    }
                )

        elif self.auth_type == WebhookAuthType.API_KEY:
            if not self.api_key:
                raise ValidationError(
                    {"api_key": "API key is required for API key authentication"}
                )
            if not self.api_key_header:
                raise ValidationError(
                    {
                        "api_key_header": "Header name is required for API key authentication"
                    }
                )
            if self.username or self.password:
                raise ValidationError(
                    {
                        "username": "Username and password should not be set for API key authentication"
                    }
                )

        elif self.auth_type == WebhookAuthType.NONE:
            if self.username or self.password or self.api_key:
                raise ValidationError(
                    {
                        "auth_type": "No credentials should be set when authentication type is 'None'"
                    }
                )

        if self.api_key_header and self.api_key_header != "X-API-Key":
            if not re.match(r"^[A-Za-z][A-Za-z0-9\-_]*$", self.api_key_header):
                raise ValidationError(
                    {
                        "api_key_header": "Invalid header name format. Must start with a letter and contain only letters, numbers, hyphens, and underscores."
                    }
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
            models.CheckConstraint(
                check=(
                    models.Q(type=WebhookType.REMOTE_COMMAND)
                    | models.Q(command_type__isnull=True)
                ),
                name="command_type_only_for_remote_command",
            ),
            models.CheckConstraint(
                check=(models.Q(auth__isnull=True) | models.Q(auth__expired=False)),
                name="webhook_auth_must_not_be_expired",
            ),
            models.UniqueConstraint(
                fields=["url"],
                condition=models.Q(active=True),
                name="unique_active_webhook_url",
            ),
        ]

    def clean(self):
        super().clean()

        if self.type == WebhookType.REMOTE_COMMAND and not self.command_type:
            raise ValidationError(
                {"command_type": "Command type is required for remote command webhooks"}
            )
        elif self.type != WebhookType.REMOTE_COMMAND and self.command_type:
            raise ValidationError(
                {
                    "command_type": "Command type should only be set for remote command webhooks"
                }
            )

        if self.auth and self.auth.expired:
            raise ValidationError(
                {"auth": "Cannot use expired authentication configuration"}
            )

    def get_auth_headers(self):
        if not self.auth or self.auth.expired:
            return {}
        return self.auth.get_auth_headers()

    def has_valid_auth(self):
        return self.auth and self.auth.is_valid_auth()

    def __str__(self):
        return f"{self.get_type_display()} - {self.url}"
