#!/usr/bin/env python3
"""Load Performix targets prepared for apx_recipe_run."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_TARGETS_FILE = Path("ci-output/performix-targets.json")

APX_ENV = (
    "ARM_MCP_SSH_KEY_PATH",
    "ARM_MCP_SSH_KNOWN_HOSTS_PATH",
    "ARM_MCP_APX_REMOTE_IP",
    "ARM_MCP_APX_REMOTE_USER",
)


def performix_configured() -> bool:
    return all(os.environ.get(name, "").strip() for name in APX_ENV)


def load_performix_targets(path: Path | str | None = None) -> dict[str, Any]:
    targets_path = Path(path or os.environ.get("ARM_MCP_APX_TARGETS") or DEFAULT_TARGETS_FILE)
    if not targets_path.is_file():
        return {"recipe": "code_hotspots", "targets": [], "errors": []}
    data = json.loads(targets_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{targets_path} must contain a JSON object")
    data.setdefault("recipe", "code_hotspots")
    data.setdefault("targets", [])
    data.setdefault("errors", [])
    return data
