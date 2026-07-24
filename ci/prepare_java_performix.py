#!/usr/bin/env python3
"""SCP Java sources to the APX host, compile with javac, and write Performix targets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
TARGETS_FILE = OUTPUT_DIR / "performix-targets.json"
DEFAULT_RECIPE = "code_hotspots"
DEFAULT_JAVA_DIR = "code/java"
DEFAULT_REMOTE_DIR = "/tmp/arm-mcp-java"
MAIN_CLASS_RE = re.compile(r"public\s+(?:final\s+)?class\s+(\w+)")
MAIN_METHOD_RE = re.compile(r"public\s+static\s+void\s+main\s*\(")

APX_ENV = (
    "ARM_MCP_SSH_KEY_PATH",
    "ARM_MCP_SSH_KNOWN_HOSTS_PATH",
    "ARM_MCP_APX_REMOTE_IP",
    "ARM_MCP_APX_REMOTE_USER",
)


def _apx_configured() -> bool:
    return all(os.environ.get(name, "").strip() for name in APX_ENV)


def _ssh_base_args(identity: Path, known_hosts: Path) -> list[str]:
    return [
        "-i",
        str(identity),
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
    ]


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"{shlex.join(cmd)}\n{output}")
    return (result.stdout or "").strip()


def _discover_java_sources(java_dir: Path) -> list[Path]:
    return sorted(path for path in java_dir.rglob("*.java") if path.is_file())


def _public_class_name(source: Path) -> str | None:
    text = source.read_text(encoding="utf-8", errors="replace")
    match = MAIN_CLASS_RE.search(text)
    return match.group(1) if match else None


def _has_main(source: Path) -> bool:
    text = source.read_text(encoding="utf-8", errors="replace")
    return bool(MAIN_METHOD_RE.search(text))


def prepare_java_performix(root: Path, java_rel: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "recipe": os.environ.get("ARM_MCP_APX_RECIPE", DEFAULT_RECIPE).strip() or DEFAULT_RECIPE,
        "language": "java",
        "source_dir": java_rel,
        "targets": [],
        "errors": [],
    }

    if not _apx_configured():
        manifest["skipped"] = "APX SSH/IP settings not configured"
        return manifest

    java_dir = (root / java_rel).resolve()
    if not java_dir.is_dir():
        manifest["errors"].append(f"Java source directory not found: {java_rel}")
        return manifest

    sources = _discover_java_sources(java_dir)
    if not sources:
        manifest["errors"].append(f"No .java files under {java_rel}")
        return manifest

    identity = Path(os.environ["ARM_MCP_SSH_KEY_PATH"].strip()).resolve()
    known_hosts = Path(os.environ["ARM_MCP_SSH_KNOWN_HOSTS_PATH"].strip()).resolve()
    remote_ip = os.environ["ARM_MCP_APX_REMOTE_IP"].strip()
    remote_user = os.environ["ARM_MCP_APX_REMOTE_USER"].strip()
    remote_dir = (
        os.environ.get("ARM_MCP_APX_REMOTE_DIR", "").strip()
        or f"{DEFAULT_REMOTE_DIR}/{os.environ.get('GITHUB_RUN_ID', 'local')}"
    )
    java_seconds = os.environ.get("ARM_MCP_APX_JAVA_SECONDS", "3").strip() or "3"

    if not identity.is_file():
        raise FileNotFoundError(f"SSH key not found: {identity}")
    if not known_hosts.is_file():
        raise FileNotFoundError(f"known_hosts not found: {known_hosts}")

    ssh_opts = _ssh_base_args(identity, known_hosts)
    remote = f"{remote_user}@{remote_ip}"
    manifest["remote_ip_addr"] = remote_ip
    manifest["remote_usr"] = remote_user
    manifest["remote_dir"] = remote_dir

    # Stage sources under public-class filenames so javac accepts them.
    staging = OUTPUT_DIR / "java-staging"
    if staging.exists():
        for old in staging.rglob("*"):
            if old.is_file():
                old.unlink()
    staging.mkdir(parents=True, exist_ok=True)

    staged: list[Path] = []
    main_classes: list[tuple[str, str]] = []  # (label, main_class)
    for source in sources:
        class_name = _public_class_name(source) or source.stem
        staged_path = staging / f"{class_name}.java"
        staged_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        staged.append(staged_path)
        if _has_main(source):
            main_classes.append((source.relative_to(root).as_posix(), class_name))

    _run(["ssh", *ssh_opts, remote, f"rm -rf {shlex.quote(remote_dir)} && mkdir -p {shlex.quote(remote_dir)}"])
    _run(["scp", *ssh_opts, *[str(path) for path in staged], f"{remote}:{remote_dir}/"])
    _run(
        [
            "ssh",
            *ssh_opts,
            remote,
            f"cd {shlex.quote(remote_dir)} && javac *.java && ls -la",
        ]
    )

    for label, main_class in main_classes:
        cmd = shlex.join(
            [
                "java",
                "-XX:+PreserveFramePointer",
                "-cp",
                remote_dir,
                main_class,
                java_seconds,
            ]
        )
        manifest["targets"].append(
            {
                "id": main_class.lower(),
                "language": "java",
                "label": label,
                "main_class": main_class,
                "cmd": cmd,
            }
        )

    if not manifest["targets"]:
        manifest["errors"].append(
            f"No Java main classes found under {java_rel}; compiled sources but nothing to profile"
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SCP Java sources to APX host, compile with javac, write Performix targets"
    )
    parser.add_argument("--root", default=os.environ.get("WORKSPACE_ROOT", os.getcwd()))
    parser.add_argument(
        "--java-dir",
        default="",
        help="Repository-relative path to Java sources",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    java_dir = args.java_dir.strip() or os.environ.get("ARM_MCP_JAVA_DIR", "").strip()
    if not java_dir:
        try:
            from detect_project import load_config

            config = load_config(root)
            performix_cfg = config.get("performix") or {}
            if isinstance(performix_cfg, dict):
                java_dir = str(performix_cfg.get("java_dir") or DEFAULT_JAVA_DIR)
                recipe = performix_cfg.get("recipe")
                if recipe and not os.environ.get("ARM_MCP_APX_RECIPE"):
                    os.environ["ARM_MCP_APX_RECIPE"] = str(recipe)
            else:
                java_dir = DEFAULT_JAVA_DIR
        except Exception:  # noqa: BLE001
            java_dir = DEFAULT_JAVA_DIR

    try:
        manifest = prepare_java_performix(root, java_dir.replace("\\", "/"))
    except Exception as exc:  # noqa: BLE001
        manifest = {
            "recipe": DEFAULT_RECIPE,
            "language": "java",
            "targets": [],
            "errors": [str(exc)],
        }

    TARGETS_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 1 if manifest.get("errors") and not manifest.get("targets") else 0


if __name__ == "__main__":
    raise SystemExit(main())
