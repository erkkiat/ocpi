"""
MCP Server Registration

This module handles MCP server tool registration following the implementation principles:
- Use MCP library decorators: @mcp_server.list_tools() and @mcp_server.call_tool()
- Return Tool objects with lowercase snake_case names and clear descriptions
- Use JSON Schema for inputSchema with oneOf for mutually exclusive parameters
- Route tool names to implementation functions in call_tool()
- Wrap exceptions and return TextContent with error messages
- Log unexpected exceptions with logger.exception()
"""

from mcp.server import Server
from mcp.types import Tool, TextContent
import logging

from .tools import get_cdr_details, list_cdrs_by_token

logger = logging.getLogger(__name__)


# Create MCP server instance
mcp_server = Server("ocpiconnector-mcp-server")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    return [
        Tool(
            name="get_cdr",
            description="Retrieve Charge Detail Record (CDR) information by UID or session ID. Returns detailed information including timing, token details, location, EVSE, session data, costs, and associated tariffs in human/AI-readable markdown format.",
            inputSchema={
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
                "oneOf": [{"required": ["uid"]}, {"required": ["session_id"]}],
            },
        ),
        Tool(
            name="list_cdrs_by_token",
            description="List Charge Detail Records (CDRs) filtered by RFID token with server-side paging (page size 20). Returns a paginated list of CDRs ordered by start_date_time with the exact query string for the next page if more results exist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pipe-separated parameters: 'rfid_token|last_cdr_uid'. Example: 'TOKEN001' for first page, 'TOKEN001|CDR-005' for next page.",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    if name == "get_cdr":
        try:
            uid = arguments.get("uid")
            session_id = arguments.get("session_id")

            result = get_cdr_details(uid=uid, session_id=session_id)

            return [TextContent(type="text", text=result)]
        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.exception("Error in get_cdr tool")
            return [TextContent(type="text", text=f"Error retrieving CDR: {str(e)}")]
    elif name == "list_cdrs_by_token":
        try:
            query = arguments.get("query", "")

            result = list_cdrs_by_token(query=query)

            return [TextContent(type="text", text=result)]
        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.exception("Error in list_cdrs_by_token tool")
            return [TextContent(type="text", text=f"Error listing CDRs: {str(e)}")]
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
