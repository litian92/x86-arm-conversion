"""Factory for creating LLM providers from config or environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from llm.anthropic import AnthropicProvider
from llm.base import LLMProvider
from llm.openai_compat import OpenAICompatProvider
from prompt_loader import load_agent_prompt

AI_CONFIG_FILENAMES = (".arm-mcp-ai.yaml", ".arm-mcp-ai.yml")


def _load_yaml_config(root: Path) -> dict[str, Any]:
    for name in AI_CONFIG_FILENAMES:
        path = root / name
        if not path.exists():
            continue
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required to parse .arm-mcp-ai.yaml. "
                "Install it with: pip install -r ci/requirements.txt"
            )
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return data
    return {}


def load_ai_config(root: Path | None = None) -> dict[str, Any]:
    """Merge AI config from YAML file and environment variables."""
    root = Path(root or os.environ.get("WORKSPACE", os.getcwd()))
    config = _load_yaml_config(root)
    llm = dict(config.get("llm") or {})

    env_overrides = {
        "provider": os.environ.get("ARM_MCP_AI_PROVIDER"),
        "model": os.environ.get("ARM_MCP_AI_MODEL"),
        "api_key_env": os.environ.get("ARM_MCP_AI_API_KEY_ENV"),
        "base_url": os.environ.get("ARM_MCP_AI_BASE_URL"),
        "max_iterations": os.environ.get("ARM_MCP_AI_MAX_ITERATIONS"),
        "temperature": os.environ.get("ARM_MCP_AI_TEMPERATURE"),
    }
    for key, value in env_overrides.items():
        if value is not None:
            if key in ("max_iterations",):
                llm[key] = int(value)
            elif key == "temperature":
                llm[key] = float(value)
            else:
                llm[key] = value

    prompt_path = config.get("prompt") or os.environ.get("ARM_MCP_AI_PROMPT_PATH")
    prompt = load_agent_prompt(root, prompt_path)
    return {"llm": llm, "prompt": prompt, "prompt_path": str(prompt_path or "")}


def create_provider(llm_config: dict[str, Any]) -> LLMProvider:
    """Instantiate an LLM provider from a config dict."""
    provider = (llm_config.get("provider") or "openai").lower()
    model = llm_config.get("model")
    if not model:
        raise ValueError("LLM model is required (set llm.model in .arm-mcp-ai.yaml or ARM_MCP_AI_MODEL)")

    api_key_env = llm_config.get("api_key_env")
    api_key = llm_config.get("api_key")
    if not api_key and api_key_env:
        api_key = os.environ.get(api_key_env, "")
    if not api_key:
        for fallback in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ARM_MCP_AI_API_KEY"):
            api_key = os.environ.get(fallback)
            if api_key:
                break

    temperature = float(llm_config.get("temperature", 0.2))
    base_url = llm_config.get("base_url")
    headers = llm_config.get("headers") or {}

    if provider in ("anthropic", "claude"):
        return AnthropicProvider(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://api.anthropic.com",
            temperature=temperature,
        )

    if provider in ("openai", "openai_compat", "ollama", "custom"):
        return OpenAICompatProvider(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            headers=headers,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM provider '{provider}'. "
        "Supported: openai, openai_compat, ollama, custom, anthropic, claude"
    )
