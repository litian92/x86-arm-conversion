"""Convert MCP tool schemas to provider-specific function-calling formats."""

from __future__ import annotations

from typing import Any


def mcp_to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to OpenAI-compatible tool format."""
    openai_tools: list[dict[str, Any]] = []
    for tool in mcp_tools:
        parameters = tool.get("inputSchema") or {"type": "object", "properties": {}}
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description") or "",
                    "parameters": parameters,
                },
            }
        )
    return openai_tools


def mcp_to_anthropic_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic tool format."""
    anthropic_tools: list[dict[str, Any]] = []
    for tool in mcp_tools:
        input_schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
        anthropic_tools.append(
            {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "input_schema": input_schema,
            }
        )
    return anthropic_tools
