"""
MCP Server Registration

This module handles MCP server tool registration following the implementation principles:
- Use MCP library decorators: @mcp_server.list_tools() and @mcp_server.call_tool()
- Return Tool objects with lowercase snake_case names and clear descriptions
- Use JSON Schema for inputSchema with oneOf for mutually exclusive parameters
- Route tool names to implementation functions in call_tool()
- Wrap exceptions and return TextContent with error messages
- Log unexpected exceptions with logger.exception()

Note: Tools are added in separate PRs. This foundation provides the infrastructure
for tool registration without any specific tool implementations.
"""

from mcp.server import Server
from mcp.types import Tool, TextContent
import logging

logger = logging.getLogger(__name__)


# Create MCP server instance
mcp_server = Server("ocpiconnector-mcp-server")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    # Tools are added in separate PRs. This foundation provides infrastructure only.
    return []


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    # Tools are added in separate PRs. This foundation provides infrastructure only.
    return [
        TextContent(
            type="text", text="No tools available. Tools will be added in separate PRs."
        )
    ]
