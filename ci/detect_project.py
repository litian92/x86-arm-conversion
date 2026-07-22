#!/usr/bin/env python3
"""Detect project languages, Docker images, and build configuration."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

LANGUAGE_MARKERS: dict[str, list[str]] = {
    "cpp": ["CMakeLists.txt", "Makefile", "*.cpp", "*.cc", "*.cxx", "*.hpp"],
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "*.py"],
    "go": ["go.mod", "*.go"],
    "js": ["package.json", "*.js", "*.ts", "*.jsx", "*.tsx"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts", "*.java"],
}

DOCKER_FROM_RE = re.compile(r"^\s*FROM\s+([^\s]+)", re.IGNORECASE | re.MULTILINE)
CONFIG_FILENAMES = (".arm-mcp-ci.yaml", ".arm-mcp-ci.yml")


def load_config(root: Path) -> dict[str, Any]:
    for name in CONFIG_FILENAMES:
        path = root / name
        if not path.exists():
            continue
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required to parse .arm-mcp-ci.yaml. "
                "Install it with: pip install -r ci/requirements.txt"
            )
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return data
    return {}


def glob_exists(root: Path, pattern: str) -> bool:
    if pattern.startswith("*."):
        return any(root.rglob(f"*{pattern[1:]}"))
    if "*" in pattern:
        return any(root.glob(pattern))
    return (root / pattern).exists()


def detect_languages(root: Path, config: dict[str, Any]) -> list[str]:
    configured = config.get("languages")
    if configured:
        return [str(lang).lower() for lang in configured]

    found: list[str] = []
    for language, markers in LANGUAGE_MARKERS.items():
        if any(glob_exists(root, marker) for marker in markers):
            found.append(language)
    return found or ["cpp"]


def find_dockerfiles(root: Path) -> list[Path]:
    return sorted(root.rglob("Dockerfile*"))


def extract_docker_images(root: Path, config: dict[str, Any]) -> list[str]:
    configured = config.get("docker_images")
    if configured:
        return [str(image) for image in configured]

    images: set[str] = set()
    for dockerfile in find_dockerfiles(root):
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
        for match in DOCKER_FROM_RE.findall(text):
            image = match.strip().strip('"').strip("'")
            if image.lower().startswith("as "):
                continue
            if image and not image.startswith("$"):
                images.add(image)
    return sorted(images)


def detect_build_commands(config: dict[str, Any]) -> dict[str, str | None]:
    build_cfg = config.get("build", {})
    if not isinstance(build_cfg, dict):
        build_cfg = {}
    return {
        "x86_64": build_cfg.get("x86_64") or build_cfg.get("x86") or build_cfg.get("amd64"),
        "arm64": build_cfg.get("arm64") or build_cfg.get("aarch64"),
        "default": build_cfg.get("default") or build_cfg.get("command"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect project metadata for ARM MCP CI")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--github-output", help="Path to GITHUB_OUTPUT for workflow outputs")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config = load_config(root)
    languages = detect_languages(root, config)
    dockerfiles = find_dockerfiles(root)
    docker_images = extract_docker_images(root, config)
    build_commands = detect_build_commands(config)

    result = {
        "languages": languages,
        "has_dockerfile": bool(dockerfiles),
        "dockerfiles": [str(path.relative_to(root)) for path in dockerfiles],
        "docker_images": docker_images,
        "build_commands": build_commands,
    }

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"languages={json.dumps(languages)}\n")
            handle.write(f"has_dockerfile={'true' if result['has_dockerfile'] else 'false'}\n")
            handle.write(f"docker_images={json.dumps(docker_images)}\n")

    if args.json or not args.github_output:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
