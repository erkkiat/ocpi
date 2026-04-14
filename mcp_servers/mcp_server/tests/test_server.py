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
from django.conf import settings


@pytest.mark.asyncio
class TestListTools:
    """Test list_tools function"""

    async def test_list_tools_returns_exactly_two_tools(self):
        tools = await list_tools()
        assert len(tools) == 2

    async def test_list_tools_get_cdr_definition_works(self):
        tools = await list_tools()
        get_cdr_tool = next((t for t in tools if t.name == "get_cdr"), None)
        assert get_cdr_tool is not None
        assert "CDR" in get_cdr_tool.description
        assert "uid" in get_cdr_tool.inputSchema["properties"]
        assert "session_id" in get_cdr_tool.inputSchema["properties"]

    async def test_list_tools_list_cdrs_by_token_definition_works(self):
        tools = await list_tools()
        list_tool = next((t for t in tools if t.name == "list_cdrs_by_token"), None)
        assert list_tool is not None
        assert "RFID token" in list_tool.description
        assert "query" in list_tool.inputSchema["properties"]
        assert "query" in list_tool.inputSchema["required"]

    async def test_list_tools_list_cdrs_by_token_description_includes_page_size(self):
        tools = await list_tools()
        list_tool = next((t for t in tools if t.name == "list_cdrs_by_token"), None)
        assert list_tool is not None
        assert str(settings.MCP_SERVER_PAGE_SIZE) in list_tool.description


@pytest.mark.asyncio
class TestCallTool:
    """Test call_tool function"""

    async def test_call_tool_get_cdr_with_uid_returns_error_for_nonexistent_cdr(self):
        result = await call_tool("get_cdr", {"uid": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_get_cdr_with_session_id_returns_text_content(self):
        result = await call_tool("get_cdr", {"session_id": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_get_cdr_value_error_returns_error_message(self):
        result = await call_tool("get_cdr", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_list_cdrs_by_token_returns_cdr_text_content(self):
        result = await call_tool("list_cdrs_by_token", {"query": "NONEXISTENT"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "CDR" in result[0].text

    async def test_call_tool_list_cdrs_by_token_value_error_returns_error_message(self):
        result = await call_tool("list_cdrs_by_token", {"query": ""})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text

    async def test_call_tool_unknown_tool_returns_unknown_tool_error(self):
        result = await call_tool("unknown_tool", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Unknown tool" in result[0].text

    async def test_call_tool_get_cdr_exception_handling_returns_text_content(self):
        # This should trigger an exception since we're not providing valid data
        result = await call_tool("get_cdr", {"uid": None})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_get_cdr_with_both_params_returns_text_content(self):
        result = await call_tool("get_cdr", {"uid": "TEST", "session_id": "TEST"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_list_cdrs_by_token_exception_handling_returns_text_content(
        self,
    ):
        result = await call_tool("list_cdrs_by_token", {"query": "invalid|format"})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    async def test_call_tool_list_cdrs_by_token_missing_query_returns_validation_error(
        self,
    ):
        # When query is not provided, should default to empty string and return validation error
        result = await call_tool("list_cdrs_by_token", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text
        # Should be a validation error, not an AttributeError about NoneType
        assert "NoneType" not in result[0].text
