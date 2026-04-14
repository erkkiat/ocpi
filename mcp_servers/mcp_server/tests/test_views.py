"""
MCP Server Views Tests

This module tests the MCP endpoint view following the implementation principles:
- Test all JSON-RPC 2.0 methods: initialize, ping, notifications/initialized, tools/list, tools/call
- Test error handling for invalid JSON, invalid JSON-RPC format, unknown methods
- Test authentication with API key
- Test both success and error cases for each tool
"""

import json
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from mcp_servers.mcp_server.models import ApiKey
from mcp.types import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)

User = get_user_model()


@pytest.mark.django_db
class TestMCPEndpoint:
    """Test MCP endpoint view"""

    @pytest.fixture
    def api_client(self):
        """Create API client with authentication"""
        client = APIClient()
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key.key}")
        return client

    def test_initialize_method_returns_server_info(self, api_client):
        """Test initialize method returns server info"""
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert "tools" in data["result"]["capabilities"]
        assert data["result"]["serverInfo"]["name"] == "ocpiconnector-mcp-server"
        assert data["id"] == 1

    def test_ping_method_returns_empty_result(self, api_client):
        """Test ping method returns empty result"""
        payload = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["result"] == {}
        assert data["id"] == 1

    def test_notifications_initialized_method_returns_204(self, api_client):
        """Test notifications/initialized method returns 204"""
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 204

    def test_tools_list_method_returns_available_tools(self, api_client):
        """Test tools/list method returns available tools"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert "tools" in data["result"]
        tools = data["result"]["tools"]
        assert len(tools) == 2
        tool_names = [tool["name"] for tool in tools]
        assert "get_cdr" in tool_names
        assert "list_cdrs_by_token" in tool_names
        assert data["id"] == 1

    def test_invalid_json_returns_400_with_jsonrpc_error_format(self, api_client):
        """Test invalid JSON returns 400 with JSON-RPC error format"""
        response = api_client.post(
            "/mcp/", data="invalid json", content_type="application/json"
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == PARSE_ERROR
        assert data["error"]["message"] == "Parse error"
        assert data["id"] is None

    def test_invalid_jsonrpc_version_returns_400_with_jsonrpc_error_format(
        self, api_client
    ):
        """Test invalid JSON-RPC version returns 400 with JSON-RPC error format"""
        payload = {
            "jsonrpc": "1.0",
            "method": "initialize",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == INVALID_REQUEST
        assert data["error"]["message"] == "Invalid Request"
        assert data["id"] is None

    def test_unknown_method_returns_error(self, api_client):
        """Test unknown method returns error"""
        payload = {
            "jsonrpc": "2.0",
            "method": "unknown_method",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == METHOD_NOT_FOUND
        assert "Method not found" in data["error"]["message"]

    def test_tools_call_unknown_tool_returns_error(self, api_client):
        """Test tools/call with unknown tool returns error"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "unknown_tool",
                "arguments": {},
            },
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == METHOD_NOT_FOUND
        assert "Unknown tool" in data["error"]["message"]

    def test_authentication_required_returns_403(self):
        """Test that authentication is required"""
        client = APIClient()
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {},
            "id": 1,
        }
        response = client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        # With @api_view decorator, authentication is enforced
        assert response.status_code == 403

    def test_mcp_api_key_does_not_grant_access_to_other_endpoints(self):
        """Test that MCP API key does not grant access to admin, OCPI, or CPO endpoints"""
        # Create MCP API key
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        # Create client with MCP API key authentication
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key.key}")

        # Test admin endpoint - should fail (admin uses Django session auth)
        response = client.get("/portal/")
        assert response.status_code in [
            401,
            403,
            302,
        ]  # Unauthorized, forbidden, or redirect to login

        # Test OCPI endpoint - should fail (OCPI uses OCPIPermission with JWT/Session/Basic auth)
        response = client.get("/ocpi/2.2.1/cdrs/")
        assert response.status_code in [401, 403]  # Unauthorized or forbidden

        # Test CPO endpoint - should fail (CPO uses same auth as OCPI)
        response = client.get("/api/cpo/v2/tariffs/")
        assert response.status_code in [401, 403]  # Unauthorized or forbidden

    def test_missing_jsonrpc_field_returns_400(self, api_client):
        """Test missing jsonrpc field returns 400"""
        payload = {
            "method": "initialize",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 400

    def test_missing_method_field_returns_400(self, api_client):
        """Test missing method field returns 400"""
        payload = {
            "jsonrpc": "2.0",
            "params": {},
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 400

    def test_get_cdr_multiple_objects_returned_returns_data_integrity_error(
        self, api_client, monkeypatch
    ):
        """Test get_cdr tool handles MultipleObjectsReturned with specific error message"""
        from django.core.exceptions import MultipleObjectsReturned

        # Monkeypatch get_cdr_details to raise MultipleObjectsReturned
        def mock_get_cdr_details(*args, **kwargs):
            raise MultipleObjectsReturned()

        monkeypatch.setattr(
            "mcp_servers.mcp_server.views.get_cdr_details", mock_get_cdr_details
        )

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_cdr",
                "arguments": {"uid": "DUPLICATE_UID"},
            },
            "id": 1,
        }
        response = api_client.post(
            "/mcp/", data=json.dumps(payload), content_type="application/json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert "data integrity issue" in data["result"]["content"][0]["text"]
        assert "Multiple CDRs found" in data["result"]["content"][0]["text"]
