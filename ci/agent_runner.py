"""AI agent loop: LLM selects and invokes Arm MCP tools dynamically."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession

from arm_mcp_client import call_tool, get_tool_schemas
from llm.base import LLMProvider, Message
from llm.schema import mcp_to_anthropic_tools, mcp_to_openai_tools


SYSTEM_PROMPT = """You are an expert Arm64 migration and performance analyst with access to Arm MCP Server tools.

Your job is to analyze codebases for x86 to Arm64 migration readiness and recommend optimizations.

Guidelines:
- Call list_tools implicitly via the schemas provided; use only the tools available to you.
- Always pass invocation_reason in every tool call (Arm MCP audit requirement).
- Workspace files are mounted at /workspace/ inside the MCP container.
- Prefer migrate_ease_scan with arch=armv8-a and output_format=json for code scans.
- For container images, use both check_image and skopeo when checking arm64 support.
- Use knowledge_base_search for Arm documentation and optimization guidance.
- Use mca on assembly (.s, .S) files for performance analysis; pass extra_args like ["-mtriple=aarch64-linux-gnu", "-mcpu=generic"].
- Chain tools as needed: scan first, then dig deeper based on findings.
- When you have gathered enough data, respond with a final structured summary (no more tool calls)."""


@dataclass
class AgentResult:
    summary: str
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)
    conversation: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    errors: list[str] = field(default_factory=list)


def _provider_tool_format(provider_name: str, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if provider_name in ("anthropic", "claude"):
        return mcp_to_anthropic_tools(mcp_tools)
    return mcp_to_openai_tools(mcp_tools)


def _truncate_result(result: Any, max_chars: int = 12000) -> str:
    text = json.dumps(result, default=str) if not isinstance(result, str) else result
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n... [truncated]"


async def run_agent(
    session: ClientSession,
    provider: LLMProvider,
    *,
    task: str,
    context: dict[str, Any] | None = None,
    max_iterations: int = 20,
    provider_name: str = "openai",
) -> AgentResult:
    """Run the tool-use loop until the LLM produces a final answer or hits max iterations."""
    mcp_tools = await get_tool_schemas(session)
    llm_tools = _provider_tool_format(provider_name, mcp_tools)

    context_block = ""
    if context:
        context_block = f"\n\nProject context:\n```json\n{json.dumps(context, indent=2)}\n```"

    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=f"{task}{context_block}"),
    ]

    tool_invocations: list[dict[str, Any]] = []
    conversation: list[dict[str, Any]] = []
    errors: list[str] = []
    final_summary = ""

    for iteration in range(1, max_iterations + 1):
        response = await provider.chat(messages, tools=llm_tools)
        conversation.append(
            {
                "iteration": iteration,
                "content": response.content,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
                ],
                "finish_reason": response.finish_reason,
            }
        )

        if not response.tool_calls:
            final_summary = response.content or ""
            return AgentResult(
                summary=final_summary,
                tool_invocations=tool_invocations,
                conversation=conversation,
                iterations=iteration,
                errors=errors,
            )

        messages.append(
            Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )

        for tool_call in response.tool_calls:
            invocation: dict[str, Any] = {
                "iteration": iteration,
                "tool": tool_call.name,
                "arguments": tool_call.arguments,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                result = await call_tool(session, tool_call.name, tool_call.arguments)
                invocation["result"] = result
                invocation["status"] = "ok"
                result_text = _truncate_result(result)
            except Exception as exc:  # noqa: BLE001
                invocation["status"] = "error"
                invocation["error"] = str(exc)
                result_text = f"Error calling {tool_call.name}: {exc}"
                errors.append(f"{tool_call.name}: {exc}")

            tool_invocations.append(invocation)
            messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )
            )

    final_summary = (
        messages[-1].content
        if messages and messages[-1].role == "assistant"
        else "Agent reached max iterations without a final summary."
    )
    errors.append(f"Stopped after {max_iterations} iterations without a final answer.")
    return AgentResult(
        summary=final_summary or "",
        tool_invocations=tool_invocations,
        conversation=conversation,
        iterations=max_iterations,
        errors=errors,
    )
