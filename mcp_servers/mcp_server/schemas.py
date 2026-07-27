"""
MCP Server Tool Schemas — Single Source of Truth

All tool definitions live here. Both views.py (HTTP JSON-RPC) and any future
transport layers should consume from this module instead of duplicating schemas.
"""

from django.conf import settings
from pydantic import BaseModel


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict


def get_get_cdr_schema() -> ToolSchema:
    return ToolSchema(
        name="get_cdr",
        description=(
            "Retrieve Charge Detail Record (CDR) information by UID or session ID. "
            "Returns detailed information including timing, token details, location, "
            "EVSE, session data, costs, and associated tariffs in "
            "human/AI-readable markdown format."
        ),
        input_schema={
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
    )


def get_list_cdrs_by_token_schema() -> ToolSchema:
    return ToolSchema(
        name="list_cdrs_by_token",
        description=(
            f"List Charge Detail Records (CDRs) filtered by RFID token with server-side "
            f"paging (page size {settings.MCP_SERVER_PAGE_SIZE}). Returns a paginated list of "
            f"CDRs ordered by start_date_time with the exact query string for the next page "
            f"if more results exist."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Pipe-separated parameters: 'rfid_token|last_cdr_uid'. "
                        "Example: 'TOKEN001' for first page, 'TOKEN001|CDR-005' for next page."
                    ),
                },
            },
            "required": ["query"],
        },
    )


def get_get_tariff_schema() -> ToolSchema:
    return ToolSchema(
        name="get_tariff",
        description=(
            "Retrieve tariff information by SolidTariff external_id or OCPI Tariff uid. "
            "Returns both the SolidTariff (master data from CPMS) and the corresponding "
            "OCPI Tariff with clear labeling to distinguish the data sources. "
            "Auto-detects the ID type."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Either SolidTariff external_id or OCPI Tariff uid",
                },
            },
            "required": ["id"],
        },
    )


def list_all_tools() -> list[ToolSchema]:
    """Return all available MCP tools in discovery order."""
    return [
        get_get_cdr_schema(),
        get_list_cdrs_by_token_schema(),
        get_get_tariff_schema(),
    ]
