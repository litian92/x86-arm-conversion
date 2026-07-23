#!/usr/bin/env python3
"""Async MCP client for the Arm MCP Server Docker image."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_IMAGE = os.environ.get("ARM_MCP_IMAGE", "armlimited/arm-mcp:latest")
DEFAULT_WORKSPACE = os.environ.get("WORKSPACE", os.getcwd())


def _docker_args(workspace: str, image: str) -> list[str]:
    workspace_path = str(Path(workspace).resolve())
    return [
        "run",
        "--rm",
        "-i",
        "-v",
        f"{workspace_path}:/workspace",
        image,
    ]


@asynccontextmanager
async def arm_mcp_session(
    workspace: str | None = None,
    image: str | None = None,
) -> AsyncIterator[ClientSession]:
    workspace = workspace or DEFAULT_WORKSPACE
    image = image or DEFAULT_IMAGE
    server_params = StdioServerParameters(
        command="docker",
        args=_docker_args(workspace, image),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    result = await session.call_tool(name, arguments or {})
    if not result.content:
        return None
    chunks: list[Any] = []
    for block in result.content:
        if hasattr(block, "text"):
            chunks.append(block.text)
        else:
            chunks.append(str(block))
    combined = "".join(chunks)
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return combined


async def get_tool_names(session: ClientSession) -> list[str]:
    tools = await session.list_tools()
    return [tool.name for tool in tools.tools]


async def get_tool_schemas(session: ClientSession) -> list[dict[str, Any]]:
    """Return MCP tool definitions as JSON-serializable dicts for LLM providers."""
    tools = await session.list_tools()
    schemas: list[dict[str, Any]] = []
    for tool in tools.tools:
        entry: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description or "",
        }
        if tool.inputSchema:
            entry["inputSchema"] = tool.inputSchema
        schemas.append(entry)
    return schemas
