"""Load agent prompts from .github/agents/*.agent.md files."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_AGENT_PROMPT = Path(".github/agents/arm-migration.agent.md")


def load_agent_prompt(root: Path | None = None, prompt_path: Path | str | None = None) -> str:
    """Read the agent prompt from a markdown file."""
    root = Path(root or os.environ.get("WORKSPACE", os.getcwd()))
    env_path = os.environ.get("ARM_MCP_AI_PROMPT_PATH")
    resolved = prompt_path or env_path or DEFAULT_AGENT_PROMPT
    path = Path(resolved)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        raise FileNotFoundError(f"Agent prompt not found: {path}")

    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Agent prompt is empty: {path}")
    return prompt
