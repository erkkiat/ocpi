"""
MCP Server View Integration

This module handles JSON-RPC 2.0 protocol in the mcp_endpoint view:
- Support methods: initialize, ping, notifications/initialized, tools/list, tools/call
- In tools/list, return tool schema from schemas.py
- In tools/call, extract tool name and arguments, call implementation function
- Return JSON-RPC 2.0 formatted responses with jsonrpc: "2.0" and id from request
- Use appropriate HTTP status codes (400 for client errors, 500 for server errors)
- Return errors in JSON-RPC format: {"error": {"code": -32601, "message": "..."}}
"""

# Standard library
import json
import logging

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from .authentication import ApiKeyAuthentication
from .schemas import list_all_tools
from .tools import get_cdr_details, list_cdrs_by_token, get_tariff_details
from mcp.types import INTERNAL_ERROR

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
            # Return the available tools from schemas.py
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for tool in list_all_tools()
            ]
            return JsonResponse(
                {"jsonrpc": "2.0", "result": {"tools": tools}, "id": request_id}
            )

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if tool_name == "get_cdr":
                return _handle_get_cdr(tool_args, request_id)
            elif tool_name == "list_cdrs_by_token":
                return _handle_list_cdrs_by_token(tool_args, request_id)
            elif tool_name == "get_tariff":
                return _handle_get_tariff(tool_args, request_id)
            else:
                return JsonResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32601,
                            "message": f"Unknown tool: {tool_name}",
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


def _handle_get_cdr(tool_args: dict, request_id):
    """Handle get_cdr tool call."""
    try:
        # Support both direct uid/session_id params and legacy query param
        uid = tool_args.get("uid")
        session_id = tool_args.get("session_id")

        # Fallback to legacy query param parsing
        if not uid and not session_id:
            query = tool_args.get("query", "")
            if query.startswith("uid:"):
                uid = query[4:]
            elif query.startswith("session_id:"):
                session_id = query[11:]
            else:
                # Try to parse as pipe-separated values
                parts = query.split("|")
                if len(parts) == 2:
                    uid = parts[0] if parts[0] else None
                    session_id = parts[1] if parts[1] else None

        result = get_cdr_details(uid=uid, session_id=session_id)

        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": result}]},
                "id": request_id,
            }
        )
    except ValueError as e:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": f"Error: {str(e)}"}]},
                "id": request_id,
            }
        )
    except ObjectDoesNotExist:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {
                    "content": [{"type": "text", "text": "Error: CDR not found"}]
                },
                "id": request_id,
            }
        )
    except MultipleObjectsReturned:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: Multiple CDRs found with the same UID - data integrity issue",
                        }
                    ]
                },
                "id": request_id,
            }
        )
    except Exception as e:
        logger.exception("Error in get_cdr tool")
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": f"Error retrieving CDR: {str(e)}",
                },
                "id": request_id,
            },
            status=500,
        )


def _handle_list_cdrs_by_token(tool_args: dict, request_id):
    """Handle list_cdrs_by_token tool call."""
    try:
        query = tool_args.get("query", "")
        result = list_cdrs_by_token(query=query)

        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": result}]},
                "id": request_id,
            }
        )
    except ValueError as e:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": f"Error: {str(e)}"}]},
                "id": request_id,
            }
        )
    except ObjectDoesNotExist:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {
                    "content": [{"type": "text", "text": "Error: CDR not found"}]
                },
                "id": request_id,
            }
        )
    except MultipleObjectsReturned:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: Multiple CDRs found with the same UID - data integrity issue",
                        }
                    ]
                },
                "id": request_id,
            }
        )
    except Exception as e:
        logger.exception("Error in list_cdrs_by_token tool")
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": f"Error listing CDRs: {str(e)}",
                },
                "id": request_id,
            },
            status=500,
        )


def _handle_get_tariff(tool_args: dict, request_id):
    """Handle get_tariff tool call."""
    try:
        tariff_id = tool_args.get("id")
        result = get_tariff_details(id=tariff_id)
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": result}]},
                "id": request_id,
            }
        )
    except ValueError as e:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": f"Error: {str(e)}"}]},
                "id": request_id,
            }
        )
    except ObjectDoesNotExist:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: Tariff not found with the provided ID",
                        }
                    ]
                },
                "id": request_id,
            }
        )
    except Exception as e:
        logger.exception("Error in get_tariff tool")
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Error retrieving tariff: {str(e)}",
                },
                "id": request_id,
            },
            status=500,
        )
