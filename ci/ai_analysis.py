#!/usr/bin/env python3
"""AI-driven Arm MCP analysis using an arbitrary LLM API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_runner import run_agent
from arm_mcp_client import arm_mcp_session, get_tool_names
from llm.factory import create_provider, load_ai_config

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
WORKSPACE = os.environ.get("WORKSPACE", os.getcwd())
LANGUAGES = json.loads(os.environ.get("LANGUAGES", "[]"))


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _build_context() -> dict[str, Any]:
    return {
        "workspace": WORKSPACE,
        "languages": LANGUAGES,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## Arm MCP AI analysis",
        "",
        f"Generated at `{report['generated_at']}`",
        f"Provider: `{report.get('llm_provider', 'unknown')}` / model: `{report.get('llm_model', 'unknown')}`",
        f"Iterations: {report.get('iterations', 0)} | Tool calls: {len(report.get('tool_invocations', []))}",
        "",
        "### Summary",
        "",
        report.get("summary") or "_No summary produced._",
        "",
    ]

    invocations = report.get("tool_invocations") or []
    if invocations:
        lines.extend(["### Tool invocations", ""])
        for inv in invocations:
            status = inv.get("status", "unknown")
            tool = inv.get("tool", "?")
            lines.append(f"- `{tool}` ({status})")
        lines.append("")

    if report.get("errors"):
        lines.extend(["### Warnings", ""])
        for error in report["errors"]:
            lines.append(f"- {error}")

    return "\n".join(lines)


async def run_ai_analysis() -> dict[str, Any]:
    config = load_ai_config(Path(WORKSPACE))
    llm_config = config["llm"]
    provider_name = (llm_config.get("provider") or "openai").lower()
    provider = create_provider(llm_config)
    max_iterations = int(llm_config.get("max_iterations", 20))

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": WORKSPACE,
        "mode": "ai",
        "llm_provider": provider_name,
        "llm_model": llm_config.get("model"),
        "tools_available": [],
        "context": _build_context(),
        "summary": "",
        "tool_invocations": [],
        "conversation": [],
        "iterations": 0,
        "errors": [],
    }

    async with arm_mcp_session(WORKSPACE) as session:
        report["tools_available"] = await get_tool_names(session)
        result = await run_agent(
            session,
            provider,
            prompt=config["prompt"],
            context=report["context"],
            max_iterations=max_iterations,
            provider_name=provider_name,
        )

    report["summary"] = result.summary
    report["tool_invocations"] = result.tool_invocations
    report["conversation"] = result.conversation
    report["iterations"] = result.iterations
    report["errors"] = result.errors
    return report


def main() -> None:
    _ensure_output_dir()
    report = asyncio.run(run_ai_analysis())
    markdown = _render_markdown(report)
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
