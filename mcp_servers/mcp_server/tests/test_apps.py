"""
MCP Server Apps Tests

This module tests Django app configuration for the MCP server.
"""

from mcp_servers.mcp_server.apps import McpServerConfig


class TestMcpServerConfig:
    """Test McpServerConfig app configuration"""

    def test_default_auto_field(self):
        """Test that default_auto_field is configured correctly"""
        assert McpServerConfig.default_auto_field == "django.db.models.BigAutoField"

    def test_app_name(self):
        """Test that app name is configured correctly"""
        assert McpServerConfig.name == "mcp_servers.mcp_server"
