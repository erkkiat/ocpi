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

Note: Tools are added in separate PRs. This foundation provides the infrastructure
for the adapter without any specific tool implementations.
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
        raise Exception(f"HTTP error: {str(e)}")


if __name__ == "__main__":
    # Run the MCP server with stdio transport
    mcp.run(transport="stdio")
