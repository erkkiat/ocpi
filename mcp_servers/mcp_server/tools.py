"""
MCP Server Tools

This module contains tool implementations following the implementation principles:
- Tool functions return markdown-formatted strings
- Use Django models directly (no mocking in tests)
- Include related data in output (tariffs, sessions, locations, etc.)
- Handle errors gracefully with clear error messages
- Use select_related/prefetch_related for query optimization

Note: Tools are added in separate PRs. This foundation provides the infrastructure
for tool registration without any specific tool implementations.
"""

# Tools are added in separate PRs
