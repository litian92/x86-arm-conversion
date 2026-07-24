#!/usr/bin/env python3
"""Async MCP client for the Arm MCP Server Docker image."""

from __future__ import annotations

import json
import os
import shlex
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_IMAGE = os.environ.get("ARM_MCP_IMAGE", "armlimited/arm-mcp:latest")
DEFAULT_WORKSPACE = os.environ.get("WORKSPACE", os.getcwd())
SSH_KEY_ENV = "ARM_MCP_SSH_KEY_PATH"
KNOWN_HOSTS_ENV = "ARM_MCP_SSH_KNOWN_HOSTS_PATH"
CONTAINER_SSH_KEY = "/run/keys/ssh_key.pem"
CONTAINER_KNOWN_HOSTS = "/run/keys/known_hosts"


def _optional_ssh_volume_mounts() -> list[str]:
    """Mount Performix SSH credentials when host paths are configured."""
    args: list[str] = []
    ssh_key_path = os.environ.get(SSH_KEY_ENV, "").strip()
    known_hosts_path = os.environ.get(KNOWN_HOSTS_ENV, "").strip()
    if ssh_key_path:
        args.extend(["-v", f"{Path(ssh_key_path).resolve()}:{CONTAINER_SSH_KEY}:ro"])
    if known_hosts_path:
        args.extend(["-v", f"{Path(known_hosts_path).resolve()}:{CONTAINER_KNOWN_HOSTS}:ro"])
    return args


def _docker_args(workspace: str, image: str) -> list[str]:
    workspace_path = str(Path(workspace).resolve())
    return [
        "run",
        "--rm",
        "-i",
        "-v",
        f"{workspace_path}:/workspace",
        *_optional_ssh_volume_mounts(),
        image,
    ]


@asynccontextmanager
async def arm_mcp_session(
    workspace: str | None = None,
    image: str | None = None,
) -> AsyncIterator[ClientSession]:
    workspace = workspace or DEFAULT_WORKSPACE
    image = image or DEFAULT_IMAGE
    docker_args = _docker_args(workspace, image)
    print(f"[arm_mcp_client] {shlex.join(['docker', *docker_args])}", flush=True)
    server_params = StdioServerParameters(
        command="docker",
        args=docker_args,
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
