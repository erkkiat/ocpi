"""
MCP Server Tests

This module tests the MCP server functions following the implementation principles:
- Test list_tools() returns correct tool definitions
- Test call_tool() routes to correct implementation functions
- Test error handling in call_tool() for ValueError and exceptions
- Test unknown tool name returns appropriate error
"""

import pytest
from mcp_servers.mcp_server.server import list_tools, call_tool
from mcp.types import TextContent


@pytest.mark.asyncio
class TestListTools:
    """Test list_tools function"""

    async def test_list_tools_returns_two_tools(self):
        """Test that list_tools returns exactly 2 tools"""
        tools = await list_tools()
        assert len(tools) == 2

    async def test_list_tools_get_cdr_definition(self):
        """Test get_cdr tool definition"""
        tools = await list_tools()
        get_cdr_tool = next((t for t in tools if t.name == "get_cdr"), None)
        assert get_cdr_tool is not None
        assert "CDR" in get_cdr_tool.description
        assert "uid" in get_cdr_tool.inputSchema["properties"]
        assert "session_id" in get_cdr_tool.inputSchema["properties"]

    async def test_list_tools_list_cdrs_by_token_definition(self):
        """Test list_cdrs_by_token tool definition"""
        tools = await list_tools()
        list_tool = next((t for t in tools if t.name == "list_cdrs_by_token"), None)
        assert list_tool is not None
        assert "RFID token" in list_tool.description
        assert "query" in list_tool.inputSchema["properties"]
        assert "query" in list_tool.inputSchema["required"]


@pytest.mark.asyncio
class TestCallTool:
    """Test call_tool function"""

    async def test_call_tool_get_cdr_with_uid(self):
        """Test call_tool for get_cdr with uid"""
        result = await call_tool("get_cdr", {"uid": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_get_cdr_with_session_id(self):
        """Test call_tool for get_cdr with session_id"""
        result = await call_tool("get_cdr", {"session_id": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_get_cdr_value_error(self):
        """Test call_tool for get_cdr with ValueError"""
        result = await call_tool("get_cdr", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_list_cdrs_by_token(self):
        """Test call_tool for list_cdrs_by_token"""
        result = await call_tool("list_cdrs_by_token", {"query": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "CDR" in result[0].text

    async def test_call_tool_list_cdrs_by_token_value_error(self):
        """Test call_tool for list_cdrs_by_token with ValueError"""
        result = await call_tool("list_cdrs_by_token", {"query": ""})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_unknown_tool(self):
        """Test call_tool with unknown tool name"""
        result = await call_tool("unknown_tool", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Unknown tool" in result[0].text

    async def test_call_tool_get_cdr_exception_handling(self):
        """Test call_tool handles exceptions in get_cdr"""
        # This should trigger an exception since we're not providing valid data
        result = await call_tool("get_cdr", {"uid": None})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_get_cdr_with_both_params(self):
        """Test call_tool for get_cdr with both uid and session_id"""
        result = await call_tool("get_cdr", {"uid": "TEST", "session_id": "TEST"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_list_cdrs_by_token_exception_handling(self):
        """Test call_tool handles exceptions in list_cdrs_by_token"""
        result = await call_tool("list_cdrs_by_token", {"query": "invalid|format"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_list_cdrs_by_token_missing_query(self):
        """Test call_tool for list_cdrs_by_token with missing query argument"""
        # When query is not provided, should default to empty string and return validation error
        result = await call_tool("list_cdrs_by_token", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text
        # Should be a validation error, not an AttributeError about NoneType
        assert "NoneType" not in result[0].text
