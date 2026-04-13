from django.contrib import admin
from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "key", "is_active", "created_at", "last_used")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "user__username", "key")
    readonly_fields = ("key", "created_at", "last_used")

    fieldsets = (
        (None, {"fields": ("name", "user", "is_active")}),
        (
            "API Key Information",
            {"fields": ("key", "created_at", "last_used"), "classes": ("collapse",)},
        ),
    )
