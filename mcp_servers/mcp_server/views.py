"""
MCP Server View Integration

This module handles JSON-RPC 2.0 protocol in the mcp_endpoint view following the implementation principles:
- Support methods: initialize, ping, notifications/initialized, tools/list, tools/call
- In tools/list, return tool schema matching server.py registration
- In tools/call, extract tool name and arguments, call implementation function
- Return JSON-RPC 2.0 formatted responses with jsonrpc: "2.0" and id from request
- Use appropriate HTTP status codes (400 for client errors, 500 for server errors)
- Return errors in JSON-RPC format: {"error": {"code": -32601, "message": "..."}}
"""

import json
import logging
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from .authentication import ApiKeyAuthentication
from .tools import get_cdr_details, list_cdrs_by_token

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
            tools = [
                {
                    "name": "get_cdr",
                    "description": "Retrieve Charge Detail Record (CDR) information by UID or session ID. Returns detailed information including timing, token details, location, EVSE, session data, costs, and associated tariffs in human/AI-readable markdown format.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "uid": {
                                "type": "string",
                                "description": "The unique identifier of the CDR (optional if session_id is provided)",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "The session ID (optional if uid is provided)",
                            },
                        },
                    },
                },
                {
                    "name": "list_cdrs_by_token",
                    "description": "List Charge Detail Records (CDRs) filtered by RFID token with server-side paging (page size 20). Returns a paginated list of CDRs ordered by start_date_time with the exact query string for the next page if more results exist.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Pipe-separated parameters: 'rfid_token|last_cdr_uid'. Example: 'TOKEN001' for first page, 'TOKEN001|CDR-005' for next page.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            ]
            return JsonResponse(
                {"jsonrpc": "2.0", "result": {"tools": tools}, "id": request_id}
            )

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if tool_name == "get_cdr":
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
                            "result": {
                                "content": [
                                    {"type": "text", "text": f"Error: {str(e)}"}
                                ]
                            },
                            "id": request_id,
                        }
                    )
                except ObjectDoesNotExist:
                    return JsonResponse(
                        {
                            "jsonrpc": "2.0",
                            "result": {
                                "content": [
                                    {"type": "text", "text": "Error: CDR not found"}
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
                                "code": -32603,
                                "message": f"Error retrieving CDR: {str(e)}",
                            },
                            "id": request_id,
                        },
                        status=500,
                    )
            elif tool_name == "list_cdrs_by_token":
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
                            "result": {
                                "content": [
                                    {"type": "text", "text": f"Error: {str(e)}"}
                                ]
                            },
                            "id": request_id,
                        }
                    )
                except ObjectDoesNotExist:
                    return JsonResponse(
                        {
                            "jsonrpc": "2.0",
                            "result": {
                                "content": [
                                    {"type": "text", "text": "Error: CDR not found"}
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
                                "code": -32603,
                                "message": f"Error listing CDRs: {str(e)}",
                            },
                            "id": request_id,
                        },
                        status=500,
                    )
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
