"""
MCP Server Tests

This module tests the MCP server functions following the implementation principles:
- Test list_tools() returns correct tool definitions
- Test call_tool() routes to correct implementation functions
- Test error handling in call_tool() for ValueError and exceptions
- Test unknown tool name returns appropriate error

Note: Tools are added in separate PRs. This foundation PR tests the infrastructure
with an empty tool list.
"""

import pytest
from mcp_servers.mcp_server.server import list_tools, call_tool
from mcp.types import TextContent


@pytest.mark.asyncio
class TestListTools:
    """Test list_tools function"""

    async def test_list_tools_returns_empty_list(self):
        """Test that list_tools returns empty list (foundation PR)"""
        tools = await list_tools()
        assert len(tools) == 0


@pytest.mark.asyncio
class TestCallTool:
    """Test call_tool function"""

    async def test_call_tool_returns_no_tools_available(self):
        """Test call_tool returns 'No tools available' message (foundation PR)"""
        result = await call_tool("any_tool", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "No tools available" in result[0].text
        assert "separate PRs" in result[0].text
