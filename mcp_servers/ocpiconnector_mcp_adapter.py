#!/usr/bin/env python3
"""
MCP Adapter for OCPI Connector

This script acts as a stdio-based MCP server that bridges Claude Desktop
to the OCPI Connector HTTP endpoint at http://localhost:8000/mcp/

Following the adapter integration principles:
- Use FastMCP for stdio-based MCP server
- Read API key and base URL from environment variables
- Implement async tool functions that call the HTTP endpoint
- Forward tool parameters to the Django endpoint via JSON-RPC
- Parse response and return text content
"""

import os
import sys
import httpx
from mcp.server.fastmcp import FastMCP

# Read configuration from environment
API_KEY = os.getenv("OCPICONNECTOR_API_KEY", "")
BASE_URL = os.getenv("OCPICONNECTOR_BASE_URL", "http://localhost:8000/mcp/")

if not API_KEY:
    print(
        "Warning: OCPICONNECTOR_API_KEY not set. Authentication may fail.",
        file=sys.stderr,
    )

# Create MCP server using FastMCP
mcp = FastMCP("ocpiconnector-mcp-server")

# HTTP client for communicating with the Django endpoint
http_client = httpx.AsyncClient(timeout=30.0)


async def call_http_endpoint(method: str, params: dict | None = None) -> dict:
    """Send request to the HTTP endpoint"""
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}

    headers = {
        "Content-Type": "application/json",
    }

    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        response = await http_client.post(BASE_URL, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"HTTP error: {str(e)}")


@mcp.tool()
async def get_tariff(id: str) -> str:
    """
    Retrieve tariff information by SolidTariff external ID or OCPI Tariff UID.

    Args:
        id: The external ID of the SolidTariff or the UID of the OCPI Tariff

    Returns:
        Markdown formatted tariff details including SolidTariff master data
        and corresponding OCPI Tariff data with clear section headers.
    """
    if not id:
        raise ValueError("ID parameter is required")

    try:
        result = await call_http_endpoint(
            "tools/call",
            {"name": "get_tariff", "arguments": {"id": id}},
        )

        if "result" in result:
            content = result["result"].get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "No data returned")
        elif "error" in result:
            raise RuntimeError(
                f"Error from server: {result['error'].get('message', 'Unknown error')}"
            )

        return "No data returned"
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve tariff: {str(e)}")


@mcp.tool()
async def get_cdr(uid: str | None = None, session_id: str | None = None) -> str:
    """
    Retrieve Charge Detail Record (CDR) information by UID or session ID.

    Args:
        uid: The unique identifier of the CDR (optional if session_id is provided)
        session_id: The session ID (optional if uid is provided)

    Returns:
        Markdown formatted CDR details including timing, token details, location,
        EVSE information, session data, costs, and associated tariffs.
    """
    if not uid and not session_id:
        raise ValueError("Either uid or session_id must be provided")

    try:
        result = await call_http_endpoint(
            "tools/call",
            {"name": "get_cdr", "arguments": {"uid": uid, "session_id": session_id}},
        )

        if "result" in result:
            content = result["result"].get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "No data returned")
        elif "error" in result:
            raise Exception(
                f"Error from server: {result['error'].get('message', 'Unknown error')}"
            )

        return "No data returned"
    except Exception as e:
        raise Exception(f"Failed to retrieve CDR: {str(e)}")


@mcp.tool()
async def list_cdrs_by_token(query: str) -> str:
    """
    List Charge Detail Records (CDRs) filtered by RFID token with server-side paging.

    Args:
        query: Pipe-separated parameters: "rfid_token|last_cdr_uid"
               Example: "TOKEN001" for first page, "TOKEN001|CDR-005" for next page

    Returns:
        Markdown formatted list of CDRs with next page query if available.
    """
    try:
        result = await call_http_endpoint(
            "tools/call",
            {"name": "list_cdrs_by_token", "arguments": {"query": query}},
        )

        if "result" in result:
            content = result["result"].get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "No data returned")
        elif "error" in result:
            raise Exception(
                f"Error from server: {result['error'].get('message', 'Unknown error')}"
            )

        return "No data returned"
    except Exception as e:
        raise Exception(f"Failed to list CDRs: {str(e)}")


if __name__ == "__main__":
    # Run the MCP server with stdio transport
    mcp.run(transport="stdio")
