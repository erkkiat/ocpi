# MCP Server for OCPI Connector

This directory contains an internal MCP (Model Context Protocol) server implementation with API key authentication, integrated as a Django view/endpoint within the ocpiconnector project.

## Overview

The MCP server provides AI agents with access to OCPI data through the MCP protocol. Tools are added in separate PRs - this foundation PR provides the infrastructure (authentication, JSON-RPC endpoint, tool registration framework) without any specific tool implementations.

## Implementation Principles

This MCP server follows the implementation principles documented in `IMPLEMENTATION_PRINCIPLES.md`. See that document for detailed guidelines on:

- Tool function design and output formatting
- Server registration and view integration
- Authentication and security
- Testing with real Django models
- Database query optimization
- Error handling
- Adding new tools

The principles document provides step-by-step instructions for implementing new MCP tools.

## Architecture

- **Authentication**: API key authentication (simple, fast, suitable for internal AI agent use)
- **Integration**: Django view/endpoint serving MCP protocol over HTTP
- **Protocol**: JSON-RPC 2.0 formatted requests
- **Database**: Uses existing Django models (Cdr, Session, Tariff) with efficient query optimization

## Installation

The MCP server is already integrated into the main Django project:

1. Added to `INSTALLED_APPS` in `ocpiconnector/settings/base.py`
2. URL routing configured in `ocpiconnector/urls.py` at `/mcp/`
3. Database migrations included in `mcp_server/migrations/`

## Usage

### Creating API Keys

1. Access Django admin at `/portal/admin/`
2. Navigate to "MCP Server" → "API Keys"
3. Create a new API key with a descriptive name (e.g., "AI Agent 1")
4. Copy the generated API key

### Making MCP Requests

The MCP endpoint accepts JSON-RPC 2.0 formatted POST requests at `/mcp/`.

**Headers:**
```
Authorization: Bearer <your_api_key>
Content-Type: application/json
```

**Example: List Available Tools**
```bash
curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }'
```

**Example: Call Tool (No Tools Available)**
```bash
curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "any_tool",
      "arguments": {}
    },
    "id": 1
  }'
```

Note: Tools are added in separate PRs. The `tools/call` endpoint will return "No tools available" until tools are implemented.

## File Structure

```
mcp-servers/
├── mcp_server/                 # Django app
│   ├── __init__.py
│   ├── apps.py                # Django app configuration
│   ├── models.py              # ApiKey model
│   ├── authentication.py      # API key authentication class
│   ├── server.py              # MCP server implementation (tool registration)
│   ├── tools.py               # Tool implementations (empty in foundation PR)
│   ├── views.py               # Django view for MCP endpoint
│   ├── urls.py                # URL routing
│   ├── admin.py               # Django admin configuration
│   ├── migrations/            # Database migrations
│   │   ├── __init__.py
│   │   └── 0001_initial.py
│   └── tests/                 # Pytest tests
│       ├── __init__.py
│       ├── test_auth.py
│       ├── test_server.py
│       └── test_views.py
├── ocpiconnector_mcp_adapter.py  # Claude Desktop adapter (empty in foundation PR)
├── IMPLEMENTATION_PRINCIPLES.md  # Tool implementation guidelines
├── claude_desktop_config.json    # Claude Desktop configuration
├── .env                         # Environment variables
└── README.md                    # This file
```

## Testing

Run tests using pytest:

```bash
# From project root
pytest mcp-servers/mcp_server/tests/
```

Tests follow the detailed guidelines in `IMPLEMENTATION_PRINCIPLES.md`, including:
- Using real Django models and queries (no mocking)
- Testing authentication flows
- Testing tool functionality
- Testing query optimization with `pytest.assertNumQueries()`

## Security

- API keys are 64-character URL-safe tokens generated using `secrets.token_urlsafe(48)`
- API keys can be deactivated via Django admin
- Last used timestamp is tracked for each API key
- Authentication required for all MCP requests
- CSRF exempt for API endpoint (uses API key authentication instead)


## Future Enhancements

Tools will be added in separate PRs. Potential tool additions:
- CDR tools (Charge Detail Records)
- Session tools
- Location tools
- Tariff tools
- Other OCPI data access tools

Each tool will be added as an independent PR that depends only on this foundation infrastructure, allowing tools to be merged in any order.

## Dependencies

- `mcp>=1.27.0` - Model Context Protocol library
- `djangorestframework` - Already in project
- Django - Already in project

## Notes

- The `venv/` directory can be removed as the project uses a shared virtual environment
- The `.env` file contains environment-specific configuration
- MCP protocol follows JSON-RPC 2.0 specification
- All responses are in markdown format for human/AI readability
