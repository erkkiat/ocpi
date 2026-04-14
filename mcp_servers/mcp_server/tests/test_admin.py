"""
MCP Server Admin Tests

This module tests Django admin configuration for the MCP server.
"""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model

from mcp_servers.mcp_server.admin import ApiKeyAdmin
from mcp_servers.mcp_server.models import ApiKey

User = get_user_model()


@pytest.mark.django_db
class TestApiKeyAdmin:
    """Test ApiKey admin configuration"""

    def test_admin_list_display_configured_correctly(self):
        """Test that admin list_display is configured correctly"""
        admin = ApiKeyAdmin(ApiKey, AdminSite())
        expected_fields = (
            "name",
            "user",
            "key",
            "is_active",
            "created_at",
            "last_used",
        )
        assert admin.list_display == expected_fields

    def test_admin_list_filter_configured_correctly(self):
        """Test that admin list_filter is configured correctly"""
        admin = ApiKeyAdmin(ApiKey, AdminSite())
        expected_filters = ("is_active", "created_at")
        assert admin.list_filter == expected_filters

    def test_admin_search_fields_configured_correctly(self):
        """Test that admin search_fields is configured correctly"""
        admin = ApiKeyAdmin(ApiKey, AdminSite())
        expected_fields = ("name", "user__username", "key")
        assert admin.search_fields == expected_fields

    def test_admin_readonly_fields_configured_correctly(self):
        """Test that admin readonly_fields is configured correctly"""
        admin = ApiKeyAdmin(ApiKey, AdminSite())
        expected_fields = ("key", "created_at", "last_used")
        assert admin.readonly_fields == expected_fields

    def test_admin_fieldsets_configured_correctly(self):
        """Test that admin fieldsets are configured correctly"""
        admin = ApiKeyAdmin(ApiKey, AdminSite())
        assert len(admin.fieldsets) == 2
        assert admin.fieldsets[0][0] is None
        assert admin.fieldsets[1][0] == "API Key Information"
