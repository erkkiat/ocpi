"""
MCP Server View Integration

This module handles JSON-RPC 2.0 protocol in the mcp_endpoint view following the implementation principles:
- Support methods: initialize, ping, notifications/initialized, tools/list, tools/call
- In tools/list, return tool schema matching server.py registration
- In tools/call, extract tool name and arguments, call implementation function
- Return JSON-RPC 2.0 formatted responses with jsonrpc: "2.0" and id from request
- Use appropriate HTTP status codes (400 for client errors, 500 for server errors)
- Return errors in JSON-RPC format: {"error": {"code": -32601, "message": "..."}}

Note: Tools are added in separate PRs. This foundation provides the infrastructure
for tool handling without any specific tool implementations.
"""

import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from .authentication import ApiKeyAuthentication

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([ApiKeyAuthentication])
@permission_classes([IsAuthenticated])
def mcp_endpoint(request):
    """
    Django view to handle MCP protocol requests.

    This endpoint accepts JSON-RPC 2.0 formatted requests for MCP protocol
    and routes them to the appropriate tool implementation.

    Expected request format (JSON-RPC 2.0):
    {
        "jsonrpc": "2.0",
        "method": "initialize" | "tools/list" | "tools/call",
        "params": {...},
        "id": 1
    }
    """
    try:
        # Parse JSON request
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                },
                status=400,
            )

        # Validate JSON-RPC format
        if data.get("jsonrpc") != "2.0":
            return JsonResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "Invalid Request"},
                    "id": None,
                },
                status=400,
            )

        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")

        # Route to appropriate method
        if method == "initialize":
            # MCP protocol handshake
            return JsonResponse(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}, "logging": {}},
                        "serverInfo": {
                            "name": "ocpiconnector-mcp-server",
                            "version": "1.0.0",
                        },
                    },
                    "id": request_id,
                }
            )

        elif method == "ping":
            # Simple ping/pong for health checks
            return JsonResponse({"jsonrpc": "2.0", "result": {}, "id": request_id})

        elif method == "notifications/initialized":
            # Notification that client initialization is complete - no response needed
            return HttpResponse(status=204)

        elif method == "tools/list":
            # Return the available tools
            # Tools are added in separate PRs. This foundation provides infrastructure only.
            tools = []
            return JsonResponse(
                {"jsonrpc": "2.0", "result": {"tools": tools}, "id": request_id}
            )

        elif method == "tools/call":
            # Tools are added in separate PRs. This foundation provides infrastructure only.
            return JsonResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": "No tools available in foundation branch",
                    },
                    "id": request_id,
                },
                status=400,
            )

        else:
            return JsonResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": request_id,
                },
                status=400,
            )

    except Exception as e:
        logger.exception("Error in MCP endpoint")
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                "id": data.get("id") if "data" in locals() else None,
            },
            status=500,
        )
