"""Load agent prompts from .github/agents/*.agent.md files."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_AGENT_PROMPT = Path(".github/agents/arm-migration.agent.md")


def _strip_outer_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _strip_frontmatter(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("---"):
        return stripped
    parts = stripped.split("---", 2)
    if len(parts) >= 3:
        return parts[2].lstrip("\n")
    return stripped


def load_agent_prompt(root: Path | None = None, prompt_path: Path | str | None = None) -> str:
    """Read the agent prompt body (YAML frontmatter stripped)."""
    root = root or Path(os.environ.get("WORKSPACE", os.getcwd()))
    env_path = os.environ.get("ARM_MCP_AI_PROMPT_PATH")
    resolved = prompt_path or env_path or DEFAULT_AGENT_PROMPT
    path = Path(resolved)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        raise FileNotFoundError(f"Agent prompt not found: {path}")

    text = path.read_text(encoding="utf-8")
    text = _strip_outer_code_fence(text)
    text = _strip_frontmatter(text)
    prompt = text.strip()
    if not prompt:
        raise ValueError(f"Agent prompt is empty: {path}")
    return prompt
