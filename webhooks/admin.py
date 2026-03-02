from django.contrib import admin
from django.template.defaultfilters import truncatechars
from django.utils.html import format_html, escape
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib import messages
from datetime import timedelta
import json

from webhooks.models import WebhookAuth, Webhook, WebhookEvent, WebhookEventStatus
from webhooks.services import WebhookExecutionService, WebhookEventService


@admin.register(WebhookAuth)
class WebhookAuthAdmin(admin.ModelAdmin):
    list_display = ["name", "auth_type", "created_at", "expired", "is_valid_indicator"]
    list_filter = ["auth_type", "expired", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        (None, {"fields": ["name", "auth_type", "expired"]}),
        (
            "Basic Authentication",
            {
                "fields": ["username", "password"],
                "classes": ["basic-auth-fields"],
                "description": 'Required when Auth Type is "Basic Authentication"',
            },
        ),
        (
            "API Authentication",
            {
                "fields": ["api_key", "api_key_header"],
                "classes": ["api-auth-fields"],
                "description": 'Required when Auth Type is "Bearer Token" or "API Key"',
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    def is_valid_indicator(self, obj):
        if obj.is_valid_auth():
            return format_html('<span style="color: green;">✓ Valid</span>')
        return format_html('<span style="color: red;">✗ Invalid</span>')

    is_valid_indicator.short_description = "Status"

    class Media:
        js = ("admin/js/webhook_auth_conditional.js",)
        css = {"all": ("admin/css/webhook_auth.css",)}


class WebhookEventInline(admin.TabularInline):
    model = WebhookEvent
    extra = 0
    readonly_fields = [
        "event_type",
        "status",
        "attempt_count",
        "created_at",
        "last_attempted_at",
        "error_message",
    ]
    fields = ["event_type", "status", "attempt_count", "created_at", "error_message"]
    can_delete = False
    show_change_link = True

    def get_queryset(self, request):
        qs = super().get_queryset(request).order_by("-created_at")
        return qs.select_related("webhook")


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "short_url",
        "type",
        "command_type",
        "active",
        "auth",
        "max_retries",
        "timeout_seconds",
        "event_stats",
        "health_indicator",
    ]
    list_filter = ["type", "command_type", "active", "created_at"]
    search_fields = ["url", "type"]
    readonly_fields = ["created_at", "updated_at", "event_statistics"]
    inlines = [WebhookEventInline]

    fieldsets = [
        (None, {"fields": ["type", "command_type", "url", "active"]}),
        ("Configuration", {"fields": ["auth", "max_retries", "timeout_seconds"]}),
        (
            "Statistics",
            {
                "fields": ["event_statistics"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
            },
        ),
    ]

    actions = [
        "activate_webhooks",
        "deactivate_webhooks",
        "test_webhooks",
        "retry_failed_events",
    ]

    @admin.display(description="URL")
    def short_url(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            obj.url,
            truncatechars(obj.url, 13),
        )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                total_events=Count("events"),
                pending_events=Count(
                    "events", filter=Q(events__status=WebhookEventStatus.PENDING)
                ),
                failed_events=Count(
                    "events", filter=Q(events__status=WebhookEventStatus.FAILED)
                ),
                success_events=Count(
                    "events", filter=Q(events__status=WebhookEventStatus.SUCCESS)
                ),
            )
        )

    def event_stats(self, obj):
        return format_html(
            '<span title="Total: {} | Success: {} | Failed: {} | Pending: {}">'
            "📊 {}/{}</span>",
            obj.total_events,
            obj.success_events,
            obj.failed_events,
            obj.pending_events,
            obj.success_events,
            obj.total_events,
        )

    event_stats.short_description = "Events (Success/Total)"
    event_stats.admin_order_field = "total_events"

    def health_indicator(self, obj):
        if obj.total_events == 0:
            return format_html('<span style="color: gray;">⚪ No events</span>')

        success_rate = (
            (obj.success_events / obj.total_events * 100) if obj.total_events > 0 else 0
        )

        if success_rate >= 95:
            return format_html(
                '<span style="color: green;">🟢 Healthy ({}%)</span>',
                round(success_rate, 1),
            )
        elif success_rate >= 80:
            return format_html(
                '<span style="color: orange;">🟡 Warning ({}%)</span>',
                round(success_rate, 1),
            )
        else:
            return format_html(
                '<span style="color: red;">🔴 Unhealthy ({}%)</span>',
                round(success_rate, 1),
            )

    health_indicator.short_description = "Health"

    def event_statistics(self, obj):
        if obj.pk:
            stats = WebhookEventService.get_pending_events(obj).aggregate(
                pending=Count("id", filter=Q(status=WebhookEventStatus.PENDING)),
                failed=Count("id", filter=Q(status=WebhookEventStatus.FAILED)),
                exhausted=Count("id", filter=Q(status=WebhookEventStatus.EXHAUSTED)),
            )

            recent_events = obj.events.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count()

            return format_html(
                "<div>"
                "<strong>Recent (7 days):</strong> {} events<br>"
                "<strong>Pending:</strong> {}<br>"
                "<strong>Failed (retryable):</strong> {}<br>"
                "<strong>Exhausted:</strong> {}"
                "</div>",
                recent_events,
                stats["pending"],
                stats["failed"],
                stats["exhausted"],
            )
        return "Save to see statistics"

    event_statistics.short_description = "Event Statistics"

    def activate_webhooks(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f"Successfully activated {updated} webhooks.")

    activate_webhooks.short_description = "Activate selected webhooks"

    def deactivate_webhooks(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f"Successfully deactivated {updated} webhooks.")

    deactivate_webhooks.short_description = "Deactivate selected webhooks"

    def test_webhooks(self, request, queryset):
        test_payload = {
            "event": "admin_test",
            "timestamp": timezone.now().isoformat(),
            "message": "Test webhook from Django admin",
        }

        total_events = 0
        for webhook in queryset.filter(active=True):
            try:
                event = WebhookEventService.create_event(
                    webhook=webhook, event_type="admin.test", payload=test_payload
                )
                WebhookExecutionService().execute_webhook_event(event)
                total_events += 1
            except Exception as e:
                messages.error(request, f"Failed to test {webhook.url}: {e}")

        if total_events > 0:
            self.message_user(
                request, f"Sent test events to {total_events} active webhooks."
            )
        else:
            self.message_user(
                request, "No active webhooks to test.", level=messages.WARNING
            )

    test_webhooks.short_description = "Send test event to selected webhooks"

    def retry_failed_events(self, request, queryset):
        total_retried = 0
        for webhook in queryset:
            retried = WebhookExecutionService.retry_failed_events(webhook_id=webhook.id)
            total_retried += retried

        if total_retried > 0:
            self.message_user(request, f"Retried {total_retried} failed events.")
        else:
            self.message_user(
                request, "No failed events to retry.", level=messages.WARNING
            )

    retry_failed_events.short_description = "Retry failed events for selected webhooks"


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "webhook_url",
        "event_type",
        "status",
        "attempt_count",
        "created_at",
        "last_attempted_at",
        "response_status_code",
    ]
    list_filter = [
        "status",
        "event_type",
        "webhook__type",
        "created_at",
        "response_status_code",
    ]
    search_fields = ["webhook__url", "event_type", "error_message"]
    date_hierarchy = "created_at"

    readonly_fields = [
        "webhook",
        "event_type",
        "payload_pretty",
        "created_at",
        "last_attempted_at",
        "completed_at",
        "response_time_ms",
    ]

    fieldsets = [
        ("Event", {"fields": ["webhook", "event_type", "status"]}),
        ("Timestamps", {"fields": ["created_at", "last_attempted_at", "completed_at"]}),
        (
            "Delivery Info",
            {
                "fields": [
                    "attempt_count",
                    "response_status_code",
                    "response_time_ms",
                    "error_message",
                ]
            },
        ),
        (
            "Payload",
            {
                "fields": ["payload_pretty"],
            },
        ),
    ]

    actions = ["retry_events", "mark_as_success", "cancel_events"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("webhook")

    def webhook_url(self, obj):
        url = reverse("admin:webhooks_webhook_change", args=[obj.webhook.id])
        return format_html('<a href="{}">{}</a>', url, obj.webhook.url)

    webhook_url.short_description = "Webhook URL"
    webhook_url.admin_order_field = "webhook__url"

    def payload_pretty(self, obj):
        if not getattr(obj, "payload", None):
            return "-"
        try:
            pretty = json.dumps(obj.payload, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.payload)

        # Use textarea instead of div for better user experience
        return format_html(
            '<textarea readonly rows="20" cols="150" '
            'style="font-family: monospace; font-size: 12px; background-color: #f8f8f8; width: 100%;">{}</textarea>',
            escape(pretty),
        )

    def retry_events(self, request, queryset):
        retried = 0
        for event in queryset.filter(status=WebhookEventStatus.FAILED):
            if event.can_retry:
                WebhookExecutionService().execute_webhook_event(event)
                retried += 1

        if retried > 0:
            self.message_user(request, f"Retried {retried} events.")
        else:
            self.message_user(
                request, "No events were eligible for retry.", level=messages.WARNING
            )

    retry_events.short_description = "Retry selected failed events"

    def mark_as_success(self, request, queryset):
        updated = 0
        for event in queryset.exclude(status=WebhookEventStatus.SUCCESS):
            WebhookEventService.mark_success(event, status_code=200)
            updated += 1

        if updated > 0:
            self.message_user(request, f"Marked {updated} events as successful.")
        else:
            self.message_user(request, "No events to update.", level=messages.WARNING)

    mark_as_success.short_description = "Mark selected events as successful"

    def cancel_events(self, request, queryset):
        cancelled = 0
        for event in queryset.filter(
            status__in=[WebhookEventStatus.PENDING, WebhookEventStatus.FAILED]
        ):
            WebhookEventService.mark_failed(
                event, "Cancelled by admin", status_code=None
            )
            event.status = WebhookEventStatus.EXHAUSTED
            event.completed_at = timezone.now()
            event.save(update_fields=["status", "completed_at"])
            cancelled += 1

        if cancelled > 0:
            self.message_user(request, f"Cancelled {cancelled} events.")
        else:
            self.message_user(request, "No events to cancel.", level=messages.WARNING)

    cancel_events.short_description = "Cancel selected pending/failed events"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
