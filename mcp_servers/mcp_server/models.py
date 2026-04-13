"""
MCP Server Models

This module contains the ApiKey model following the implementation principles:
- Generate 64-character URL-safe keys using secrets.token_urlsafe(48)
- Auto-generate key on save if not provided
- Track created_at and last_used timestamps
- Link to Django User model
- Support is_active flag for key deactivation
"""

import secrets
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _


User = get_user_model()


class ApiKey(models.Model):
    """API key for authenticating MCP clients (AI agents)"""

    objects: models.Manager["ApiKey"] = models.Manager()

    key = models.CharField(
        max_length=64, unique=True, db_index=True, verbose_name=_("API Key")
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="api_keys", verbose_name=_("User")
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Name"),
        help_text=_("Descriptive name for this API key (e.g., 'AI Agent 1')"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    last_used = models.DateTimeField(null=True, blank=True, verbose_name=_("Last used"))

    class Meta:
        verbose_name = _("API Key")
        verbose_name_plural = _("API Keys")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_key():
        """Generate a secure random API key"""
        return secrets.token_urlsafe(48)

    def update_last_used(self):
        """Update the last_used timestamp"""
        from django.utils import timezone

        self.last_used = timezone.now()
        self.save(update_fields=["last_used"])
