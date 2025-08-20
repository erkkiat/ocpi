import pytest
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import IntegrityError
import time_machine

from webhooks.models import (
    WebhookAuth,
    Webhook,
    WebhookEvent,
    WebhookAuthType,
    WebhookEventStatus,
    WebhookEventType,
    WebhookAuthValidator,
    WebhookValidator,
)
from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.factories import WebhookAuthFactory, WebhookFactory, WebhookEventFactory


class TestWebhookAuthType:
    def test_webhook_auth_type_choices_contain_expected_values(self):
        expected_choices = [
            ("none", "No Authentication"),
            ("basic", "Basic Authentication"),
            ("bearer", "Bearer Token"),
            ("api_key", "API Key"),
        ]
        assert WebhookAuthType.choices == expected_choices

    def test_webhook_auth_type_default_values(self):
        assert WebhookAuthType.NONE == "none"
        assert WebhookAuthType.BASIC == "basic"
        assert WebhookAuthType.BEARER == "bearer"
        assert WebhookAuthType.API_KEY == "api_key"


class TestWebhookAuthValidator:
    @pytest.mark.parametrize(
        "auth_type,username,password,api_key,api_key_header,should_raise",
        [
            (WebhookAuthType.BASIC, "user", "pass", "", "", False),
            (WebhookAuthType.BASIC, "", "pass", "", "", True),
            (WebhookAuthType.BASIC, "user", "", "", "", True),
            (WebhookAuthType.BASIC, "", "", "", "", True),
            (WebhookAuthType.BEARER, "", "", "token123", "", False),
            (WebhookAuthType.BEARER, "", "", "", "", True),
            (WebhookAuthType.API_KEY, "", "", "key123", "X-API-Key", False),
            (WebhookAuthType.API_KEY, "", "", "", "X-API-Key", True),
            (WebhookAuthType.API_KEY, "", "", "key123", "", True),
            (WebhookAuthType.NONE, "", "", "", "", False),
        ],
    )
    def test_validate_required_fields_with_various_combinations(
        self, auth_type, username, password, api_key, api_key_header, should_raise
    ):
        if should_raise:
            with pytest.raises(ValidationError):
                WebhookAuthValidator.validate_required_fields(
                    auth_type, username, password, api_key, api_key_header
                )
        else:
            WebhookAuthValidator.validate_required_fields(
                auth_type, username, password, api_key, api_key_header
            )

    @pytest.mark.parametrize(
        "api_key_header,should_raise",
        [
            ("X-API-Key", False),
            ("", False),
            ("ValidHeader", False),
            ("Valid-Header", False),
            ("Valid_Header", False),
            ("Valid123", False),
            ("123Invalid", True),
            ("Invalid-Header!", True),
            ("Invalid Header", True),
            ("-InvalidStart", True),
        ],
    )
    def test_validate_api_key_header_format_with_various_headers(
        self, api_key_header, should_raise
    ):
        if should_raise:
            with pytest.raises(ValidationError):
                WebhookAuthValidator.validate_api_key_header_format(api_key_header)
        else:
            WebhookAuthValidator.validate_api_key_header_format(api_key_header)


@pytest.mark.django_db
class TestWebhookValidator:
    def test_validate_remote_command_requirements_raises_when_command_type_missing(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            WebhookValidator.validate_remote_command_requirements(
                WebhookType.REMOTE_COMMAND, ""
            )
        assert "Command type is required for remote command webhooks" in str(
            exc_info.value
        )

    def test_validate_remote_command_requirements_passes_when_command_type_provided(
        self,
    ):
        WebhookValidator.validate_remote_command_requirements(
            WebhookType.REMOTE_COMMAND, RemoteCommandType.START_SESSION
        )

    def test_validate_remote_command_requirements_passes_for_non_remote_command_webhooks(
        self,
    ):
        WebhookValidator.validate_remote_command_requirements(WebhookType.INVOICING, "")

    def test_validate_auth_not_expired_raises_when_auth_expired(self):
        auth = WebhookAuthFactory(expired=True)
        with pytest.raises(ValidationError) as exc_info:
            WebhookValidator.validate_auth_not_expired(auth)
        assert "Cannot use expired authentication configuration" in str(exc_info.value)

    def test_validate_auth_not_expired_passes_when_auth_not_expired(self):
        auth = WebhookAuthFactory(expired=False)
        WebhookValidator.validate_auth_not_expired(auth)

    def test_validate_auth_not_expired_passes_when_auth_is_none(self):
        WebhookValidator.validate_auth_not_expired(None)

    @patch.object(WebhookValidator, "MAX_ACTIVE_WEBHOOKS_PER_TYPE", 2)
    def test_validate_webhook_activation_limits_raises_when_limit_exceeded(self):
        WebhookFactory(type=WebhookType.INVOICING, active=True)
        WebhookFactory(type=WebhookType.INVOICING, active=True)

        new_webhook = WebhookFactory.build(type=WebhookType.INVOICING, active=True)

        with pytest.raises(ValidationError) as exc_info:
            WebhookValidator.validate_webhook_activation_limits(new_webhook)
        assert "Cannot activate webhook. Maximum 2 active webhooks allowed" in str(
            exc_info.value
        )

    @patch.object(WebhookValidator, "MAX_ACTIVE_WEBHOOKS_PER_TYPE", 2)
    def test_validate_webhook_activation_limits_passes_when_under_limit(self):
        WebhookFactory(type=WebhookType.INVOICING, active=True)

        new_webhook = WebhookFactory.build(type=WebhookType.INVOICING, active=True)
        WebhookValidator.validate_webhook_activation_limits(new_webhook)

    @patch.object(WebhookValidator, "MAX_ACTIVE_WEBHOOKS_PER_TYPE", 2)
    def test_validate_webhook_activation_limits_passes_when_webhook_inactive(self):
        WebhookFactory(type=WebhookType.INVOICING, active=True)
        WebhookFactory(type=WebhookType.INVOICING, active=True)

        new_webhook = WebhookFactory.build(type=WebhookType.INVOICING, active=False)
        WebhookValidator.validate_webhook_activation_limits(new_webhook)

    @patch.object(WebhookValidator, "MAX_ACTIVE_WEBHOOKS_PER_TYPE", 2)
    def test_validate_webhook_activation_limits_excludes_current_webhook_from_count(
        self,
    ):
        webhook = WebhookFactory(type=WebhookType.INVOICING, active=True)
        WebhookFactory(type=WebhookType.INVOICING, active=True)

        webhook.active = True
        WebhookValidator.validate_webhook_activation_limits(webhook)


@pytest.mark.django_db
class TestWebhookAuth:
    def test_webhook_auth_creation_with_basic_auth(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BASIC,
            username="testuser",
            password="testpass",
        )
        assert auth.name
        assert auth.auth_type == WebhookAuthType.BASIC
        assert auth.username == "testuser"
        assert auth.password == "testpass"
        assert not auth.expired

    def test_webhook_auth_creation_with_bearer_token(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="bearer_token_123",
        )
        assert auth.auth_type == WebhookAuthType.BEARER
        assert auth.api_key == "bearer_token_123"

    def test_webhook_auth_creation_with_api_key(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.API_KEY,
            api_key="api_key_123",
            api_key_header="X-Custom-Key",
        )
        assert auth.auth_type == WebhookAuthType.API_KEY
        assert auth.api_key == "api_key_123"
        assert auth.api_key_header == "X-Custom-Key"

    def test_webhook_auth_clean_validates_configuration(self):
        auth = WebhookAuthFactory.build(
            auth_type=WebhookAuthType.BASIC,
            username="",
            password="",
        )
        with pytest.raises(ValidationError):
            auth.clean()

    def test_webhook_auth_get_auth_headers_returns_basic_auth_header(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BASIC,
            username="testuser",
            password="testpass",
        )
        headers = auth.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

    def test_webhook_auth_get_auth_headers_returns_bearer_token_header(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="token123",
        )
        headers = auth.get_auth_headers()
        assert headers["Authorization"] == "Bearer token123"

    def test_webhook_auth_get_auth_headers_returns_api_key_header(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.API_KEY,
            api_key="key123",
            api_key_header="X-Custom-Key",
        )
        headers = auth.get_auth_headers()
        assert headers["X-Custom-Key"] == "key123"

    def test_webhook_auth_get_auth_headers_returns_empty_dict_for_none_auth(self):
        auth = WebhookAuthFactory(auth_type=WebhookAuthType.NONE)
        headers = auth.get_auth_headers()
        assert headers == {}

    def test_webhook_auth_get_auth_headers_returns_empty_dict_when_missing_credentials(
        self,
    ):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BASIC,
            username="",
            password="",
        )
        headers = auth.get_auth_headers()
        assert headers == {}

    def test_webhook_auth_is_valid_auth_returns_true_when_valid(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="token123",
            expired=False,
        )
        assert auth.is_valid_auth()

    def test_webhook_auth_is_valid_auth_returns_false_when_expired(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="token123",
            expired=True,
        )
        assert not auth.is_valid_auth()

    def test_webhook_auth_is_valid_auth_returns_false_when_no_credentials(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BASIC,
            username="",
            password="",
            expired=False,
        )
        assert not auth.is_valid_auth()

    def test_webhook_auth_str_representation(self):
        auth = WebhookAuthFactory(
            name="Production API",
            auth_type=WebhookAuthType.BEARER,
        )
        assert str(auth) == "Production API (Bearer Token)"

    def test_webhook_auth_unique_name_constraint(self):
        WebhookAuthFactory(name="Unique Name")
        with pytest.raises(IntegrityError):
            WebhookAuthFactory(name="Unique Name")


@pytest.mark.django_db
class TestWebhook:
    def test_webhook_creation_with_minimal_fields(self):
        webhook = WebhookFactory(
            type=WebhookType.INVOICING,
            url="https://example.com/webhook",
            active=False,
        )
        assert webhook.type == WebhookType.INVOICING
        assert webhook.url == "https://example.com/webhook"
        assert webhook.max_retries == 3
        assert webhook.timeout_seconds == 30
        assert not webhook.active

    def test_webhook_creation_with_remote_command_type(self):
        webhook = WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.START_SESSION,
        )
        assert webhook.type == WebhookType.REMOTE_COMMAND
        assert webhook.command_type == RemoteCommandType.START_SESSION

    def test_webhook_creation_with_auth(self):
        auth = WebhookAuthFactory()
        webhook = WebhookFactory(auth=auth)
        assert webhook.auth == auth

    def test_webhook_clean_validates_remote_command_requirements(self):
        webhook = WebhookFactory.build(
            type=WebhookType.REMOTE_COMMAND,
            command_type=None,
        )
        with pytest.raises(ValidationError):
            webhook.clean()

    @patch.object(WebhookValidator, "MAX_ACTIVE_WEBHOOKS_PER_TYPE", 1)
    def test_webhook_clean_validates_activation_limits(self):
        WebhookFactory(type=WebhookType.INVOICING, active=True)
        webhook = WebhookFactory.build(type=WebhookType.INVOICING, active=True)
        with pytest.raises(ValidationError):
            webhook.clean()

    def test_webhook_get_auth_headers_returns_auth_headers_when_auth_exists(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="token123",
        )
        webhook = WebhookFactory(auth=auth)
        headers = webhook.get_auth_headers()
        assert headers["Authorization"] == "Bearer token123"

    def test_webhook_get_auth_headers_returns_empty_dict_when_no_auth(self):
        webhook = WebhookFactory(auth=None)
        headers = webhook.get_auth_headers()
        assert headers == {}

    def test_webhook_get_auth_headers_returns_empty_dict_when_auth_expired(self):
        auth = WebhookAuthFactory(expired=True)
        webhook = WebhookFactory.build(auth=auth)
        headers = webhook.get_auth_headers()
        assert headers == {}

    def test_webhook_has_valid_auth_returns_true_when_auth_valid(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="token123",
            expired=False,
        )
        webhook = WebhookFactory(auth=auth)
        assert webhook.has_valid_auth()

    def test_webhook_has_valid_auth_returns_false_when_no_auth(self):
        webhook = WebhookFactory(auth=None)
        assert not webhook.has_valid_auth()

    def test_webhook_has_valid_auth_returns_false_when_auth_invalid(self):
        auth = WebhookAuthFactory(expired=True)
        webhook = WebhookFactory.build(auth=auth)
        assert not webhook.has_valid_auth()

    def test_webhook_str_representation(self):
        webhook = WebhookFactory(
            type=WebhookType.INVOICING,
            url="https://example.com/webhook",
        )
        assert str(webhook) == "Invoicing - https://example.com/webhook"

    def test_webhook_unique_active_url_constraint(self):
        WebhookFactory(url="https://example.com/webhook", active=True)
        with pytest.raises(ValidationError):
            WebhookFactory(url="https://example.com/webhook", active=True)

    def test_webhook_allows_duplicate_inactive_urls(self):
        WebhookFactory(url="https://example.com/webhook", active=False)
        WebhookFactory(url="https://example.com/webhook", active=False)

    def test_webhook_allows_same_url_if_previous_deactivated(self):
        webhook1 = WebhookFactory(url="https://example.com/webhook", active=True)
        webhook1.active = False
        webhook1.save()
        WebhookFactory(url="https://example.com/webhook", active=True)

    @pytest.mark.parametrize(
        "max_retries,is_valid",
        [
            (0, True),
            (5, True),
            (10, True),
            (11, False),
        ],
    )
    def test_webhook_max_retries_validation(self, max_retries, is_valid):
        if is_valid:
            WebhookFactory(max_retries=max_retries)
        else:
            with pytest.raises(ValidationError):
                webhook = WebhookFactory.build(max_retries=max_retries)
                webhook.full_clean()

    @pytest.mark.parametrize(
        "timeout_seconds,is_valid",
        [
            (1, True),
            (30, True),
            (180, True),
            (0, False),
            (181, False),
        ],
    )
    def test_webhook_timeout_seconds_validation(self, timeout_seconds, is_valid):
        if is_valid:
            WebhookFactory(timeout_seconds=timeout_seconds)
        else:
            with pytest.raises(ValidationError):
                webhook = WebhookFactory.build(timeout_seconds=timeout_seconds)
                webhook.full_clean()


class TestWebhookEventStatus:
    def test_webhook_event_status_choices_contain_expected_values(self):
        expected_choices = [
            ("pending", "Pending"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("exhausted", "Retries Exhausted"),
        ]
        assert WebhookEventStatus.choices == expected_choices


class TestWebhookEventType:
    def test_webhook_event_type_constants_are_strings(self):
        assert isinstance(WebhookEventType.CHARGE_POINT_STATUS_CHANGED, str)
        assert isinstance(WebhookEventType.SESSION_STARTED, str)
        assert isinstance(WebhookEventType.TOKEN_AUTHORIZED, str)

    def test_get_all_standard_types_returns_all_event_types(self):
        standard_types = WebhookEventType.get_all_standard_types()
        assert WebhookEventType.CHARGE_POINT_STATUS_CHANGED in standard_types
        assert WebhookEventType.SESSION_STARTED in standard_types
        assert WebhookEventType.TOKEN_AUTHORIZED in standard_types
        assert WebhookEventType.INVOICE_GENERATED in standard_types

    def test_is_standard_type_returns_true_for_standard_types(self):
        assert WebhookEventType.is_standard_type(
            WebhookEventType.CHARGE_POINT_STATUS_CHANGED
        )
        assert WebhookEventType.is_standard_type(WebhookEventType.SESSION_STARTED)

    def test_is_standard_type_returns_false_for_custom_types(self):
        assert not WebhookEventType.is_standard_type("custom.event.type")
        assert not WebhookEventType.is_standard_type("unknown_event")


@pytest.mark.django_db
class TestWebhookEvent:
    def test_webhook_event_creation_with_minimal_fields(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.SESSION_STARTED,
            payload={"session_id": "123"},
        )
        assert event.webhook == webhook
        assert event.event_type == WebhookEventType.SESSION_STARTED
        assert event.payload == {"session_id": "123"}
        assert event.status == WebhookEventStatus.PENDING
        assert event.attempt_count == 0

    def test_webhook_event_creation_with_all_fields(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(
            webhook=webhook,
            event_type=WebhookEventType.TOKEN_AUTHORIZED,
            payload={"token_id": "abc123"},
            status=WebhookEventStatus.SUCCESS,
            attempt_count=2,
            error_message="Previous error",
            response_status_code=200,
            response_time_ms=150,
        )
        assert event.status == WebhookEventStatus.SUCCESS
        assert event.attempt_count == 2
        assert event.error_message == "Previous error"
        assert event.response_status_code == 200
        assert event.response_time_ms == 150

    @time_machine.travel("2023-01-01 12:00:00+00:00")
    def test_webhook_event_auto_timestamps(self):
        event = WebhookEventFactory()
        assert event.created_at.isoformat().startswith("2023-01-01T12:00:00")

    def test_webhook_event_can_retry_returns_true_when_under_max_retries(self):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=2)
        assert event.can_retry

    def test_webhook_event_can_retry_returns_false_when_at_max_retries(self):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=3)
        assert not event.can_retry

    def test_webhook_event_can_retry_returns_false_when_over_max_retries(self):
        webhook = WebhookFactory(max_retries=3)
        event = WebhookEventFactory(webhook=webhook, attempt_count=5)
        assert not event.can_retry

    @pytest.mark.parametrize(
        "status,is_completed",
        [
            (WebhookEventStatus.PENDING, False),
            (WebhookEventStatus.FAILED, False),
            (WebhookEventStatus.SUCCESS, True),
            (WebhookEventStatus.EXHAUSTED, True),
        ],
    )
    def test_webhook_event_is_completed_property(self, status, is_completed):
        event = WebhookEventFactory(status=status)
        assert event.is_completed == is_completed

    def test_webhook_event_str_representation(self):
        webhook = WebhookFactory(url="https://example.com/webhook")
        event = WebhookEventFactory(
            webhook=webhook,
            status=WebhookEventStatus.SUCCESS,
        )
        expected = f"WebhookEvent {event.id} - https://example.com/webhook (success)"
        assert str(event) == expected

    def test_webhook_event_ordering_by_created_at_desc(self):
        webhook = WebhookFactory()
        with time_machine.travel("2023-01-01 12:00:00+00:00"):
            event1 = WebhookEventFactory(webhook=webhook)
        with time_machine.travel("2023-01-01 13:00:00+00:00"):
            event2 = WebhookEventFactory(webhook=webhook)

        events = list(WebhookEvent.objects.all())
        assert events[0] == event2
        assert events[1] == event1

    def test_webhook_event_indexes_exist(self):
        indexes = [index.fields for index in WebhookEvent._meta.indexes]
        assert ["webhook", "status"] in indexes
        assert ["status", "created_at"] in indexes
        assert ["event_type"] in indexes

    def test_webhook_event_cascade_delete_with_webhook(self):
        webhook = WebhookFactory()
        event = WebhookEventFactory(webhook=webhook)
        webhook_id = webhook.id
        event_id = event.id

        webhook.delete()

        assert not Webhook.objects.filter(id=webhook_id).exists()
        assert not WebhookEvent.objects.filter(id=event_id).exists()

    def test_webhook_event_related_name_works(self):
        webhook = WebhookFactory()
        event1 = WebhookEventFactory(webhook=webhook)
        event2 = WebhookEventFactory(webhook=webhook)

        events = webhook.events.all()
        assert event1 in events
        assert event2 in events
        assert events.count() == 2


@pytest.mark.django_db
class TestWebhookModelConstraints:
    def test_webhook_auth_api_key_constraint_enforced(self):
        with pytest.raises(IntegrityError):
            WebhookAuth.objects.create(
                name="Test Auth",
                auth_type=WebhookAuthType.API_KEY,
                api_key="key123",
                api_key_header="",
            )

    def test_webhook_auth_api_key_constraint_allows_valid_combination(self):
        auth = WebhookAuth.objects.create(
            name="Test Auth",
            auth_type=WebhookAuthType.API_KEY,
            api_key="key123",
            api_key_header="X-API-Key",
        )
        assert auth.id

    def test_webhook_remote_command_constraint_enforced(self):
        with pytest.raises(ValidationError):
            Webhook.objects.create(
                type=WebhookType.REMOTE_COMMAND,
                url="https://example.com/webhook",
                command_type=None,
            )

    def test_webhook_remote_command_constraint_allows_valid_combination(self):
        webhook = Webhook.objects.create(
            type=WebhookType.REMOTE_COMMAND,
            url="https://example.com/webhook",
            command_type=RemoteCommandType.START_SESSION,
        )
        assert webhook.id


@pytest.mark.django_db
class TestWebhookModelIntegration:
    def test_webhook_with_auth_integration(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="integration_token",
        )
        webhook = WebhookFactory(auth=auth)

        headers = webhook.get_auth_headers()
        assert headers["Authorization"] == "Bearer integration_token"
        assert webhook.has_valid_auth()

    def test_webhook_event_with_webhook_integration(self):
        webhook = WebhookFactory(max_retries=5)
        event = WebhookEventFactory(
            webhook=webhook,
            attempt_count=3,
            status=WebhookEventStatus.FAILED,
        )

        assert event.can_retry
        assert not event.is_completed
        assert event.webhook.max_retries == 5

    def test_webhook_deactivation_flow(self):
        webhook = WebhookFactory(active=True)
        WebhookEventFactory(webhook=webhook, status=WebhookEventStatus.SUCCESS)
        WebhookEventFactory(webhook=webhook, status=WebhookEventStatus.FAILED)

        webhook.active = False
        webhook.save()

        assert not webhook.active
        assert webhook.events.count() == 2

    def test_auth_expiration_flow(self):
        auth = WebhookAuthFactory(
            auth_type=WebhookAuthType.BEARER,
            api_key="BEST-SECRET-KEY",
            expired=False,
        )
        webhook = WebhookFactory(auth=auth)
        assert webhook.has_valid_auth()

        auth.expired = True
        auth.save()

        webhook.refresh_from_db()
        assert not webhook.has_valid_auth()
        assert webhook.get_auth_headers() == {}
