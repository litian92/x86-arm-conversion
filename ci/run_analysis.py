#!/usr/bin/env python3
"""Run Arm MCP Server tools and produce a CI analysis report."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arm_mcp_client import arm_mcp_session, call_tool, get_tool_names
from migrate_ease_parse import format_finding, iter_issues_from_scan
from suggestion_builder import build_inline_suggestions

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
WORKSPACE = os.environ.get("WORKSPACE", os.getcwd())
LANGUAGES = json.loads(os.environ.get("LANGUAGES", "[]"))
DOCKER_IMAGES = json.loads(os.environ.get("DOCKER_IMAGES", "[]"))

OBJECT_SUFFIXES = {".s", ".S"}
OPTIMIZATION_QUERIES = [
    "Arm64 performance optimization best practices",
    "x86 to Arm64 intrinsic migration",
    "NEON SIMD optimization for Arm",
]


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _finding_count(scan_result: dict[str, Any]) -> int:
    parsed = scan_result.get("parsed_results")
    if isinstance(parsed, dict):
        total = parsed.get("total_issue_count")
        if isinstance(total, int):
            return total
        issues = parsed.get("issues")
        if isinstance(issues, list):
            return len(issues)
        for key in ("findings", "issues", "results", "matches"):
            value = parsed.get(key)
            if isinstance(value, list):
                return len(value)
        return len(parsed)
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _extract_finding_summaries(scan_result: dict[str, Any], limit: int = 10) -> list[str]:
    summaries: list[str] = []
    for item in iter_issues_from_scan(scan_result):
        if len(summaries) >= limit:
            break
        summaries.append(format_finding(item))
    return summaries


def _discover_object_files(root: Path, limit: int = 5) -> list[str]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if path.suffix.lower() in OBJECT_SUFFIXES and path.is_file():
            candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_size if item.exists() else 0, reverse=True)
    rel_paths: list[str] = []
    for path in candidates[:limit]:
        try:
            rel_paths.append(str(path.relative_to(root)))
        except ValueError:
            rel_paths.append(str(path))
    return rel_paths


async def run_analysis() -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": WORKSPACE,
        "tools_available": [],
        "migrate_ease_scans": {},
        "docker_checks": {},
        "mca_analyses": {},
        "knowledge_base": [],
        "optimization_suggestions": [],
        "errors": [],
    }

    async with arm_mcp_session(WORKSPACE) as session:
        report["tools_available"] = await get_tool_names(session)

        for language in LANGUAGES:
            try:
                scan = await call_tool(
                    session,
                    "migrate_ease_scan",
                    {
                        "scanner": language,
                        "arch": "armv8-a",
                        "output_format": "json",
                        "invocation_reason": f"CI scan for {language} Arm compatibility",
                    },
                )
                report["migrate_ease_scans"][language] = scan
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"migrate_ease_scan({language}): {exc}")

        for image in DOCKER_IMAGES:
            docker_report: dict[str, Any] = {}
            for tool_name in ("check_image", "skopeo"):
                try:
                    docker_report[tool_name] = await call_tool(
                        session,
                        tool_name,
                        {
                            "image": image,
                            "invocation_reason": f"CI container architecture check for {image}",
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"{tool_name}({image}): {exc}")
            report["docker_checks"][image] = docker_report

        object_files = _discover_object_files(Path(WORKSPACE))
        for rel_path in object_files:
            container_path = f"/workspace/{rel_path.replace(os.sep, '/')}"
            try:
                report["mca_analyses"][rel_path] = await call_tool(
                    session,
                    "mca",
                    {
                        "input_path": container_path,
                        # Arm MCP maps triple/cpu to unsupported --triple/--mcpu flags.
                        # llvm-mca expects -mtriple= and -mcpu= via extra_args.
                        "extra_args": [
                            "-mtriple=aarch64-linux-gnu",
                            "-mcpu=generic",
                        ],
                        "invocation_reason": "CI assembly performance analysis for Arm64",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"mca({rel_path}): {exc}")

        for query in OPTIMIZATION_QUERIES:
            try:
                results = await call_tool(
                    session,
                    "knowledge_base_search",
                    {
                        "query": query,
                        "invocation_reason": "CI performance optimization guidance",
                    },
                )
                report["knowledge_base"].append({"query": query, "results": results})
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"knowledge_base_search({query}): {exc}")

    report["optimization_suggestions"] = _build_optimization_suggestions(report)
    report["inline_suggestions"] = build_inline_suggestions(report, Path(WORKSPACE))
    return report


def _build_optimization_suggestions(report: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []

    for language, scan in report.get("migrate_ease_scans", {}).items():
        if not isinstance(scan, dict):
            continue
        count = _finding_count(scan)
        if count:
            suggestions.append(
                f"Address {count} migrate-ease finding(s) in {language} code before expecting optimal Arm64 performance."
            )
            for summary in _extract_finding_summaries(scan, limit=5):
                suggestions.append(f"{language}: {summary}")

    for image, checks in report.get("docker_checks", {}).items():
        check_image = checks.get("check_image") if isinstance(checks, dict) else None
        if isinstance(check_image, dict):
            architectures = check_image.get("architectures") or check_image.get("supported_architectures")
            if isinstance(architectures, list) and "arm64" not in architectures and "arm64/v8" not in architectures:
                suggestions.append(
                    f"Container image `{image}` may not publish arm64 builds. Prefer a multi-arch base image."
                )

    if report.get("mca_analyses"):
        suggestions.append(
            "Review LLVM-MCA output for hot assembly paths; consider NEON intrinsics or compiler flags such as `-mcpu=native` on Arm runners."
        )
    else:
        suggestions.append(
            "Add assembly (.s) files or build with `-S` to enable LLVM-MCA analysis on hot paths."
        )

    for entry in report.get("knowledge_base", []):
        results = entry.get("results")
        if not isinstance(results, list):
            continue
        for item in results[:2]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("url") or "Arm documentation"
            url = item.get("url")
            snippet = str(item.get("text") or item.get("snippet") or "")[:180]
            line = f"See `{title}`"
            if url:
                line += f" ({url})"
            if snippet:
                line += f": {snippet}"
            suggestions.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        if suggestion not in seen:
            seen.add(suggestion)
            deduped.append(suggestion)
    return deduped[:20]


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## Arm MCP analysis",
        "",
        f"Generated at `{report['generated_at']}`",
        "",
    ]

    if report.get("migrate_ease_scans"):
        lines.extend(["### Migration compatibility (migrate-ease)", ""])
        for language, scan in report["migrate_ease_scans"].items():
            if not isinstance(scan, dict):
                lines.append(f"- **{language}**: scan failed")
                continue
            status = scan.get("status", "unknown")
            count = _finding_count(scan)
            lines.append(f"- **{language}**: {status}, {count} finding(s)")
            for summary in _extract_finding_summaries(scan, limit=3):
                lines.append(f"  - {summary}")
        lines.append("")

    if report.get("docker_checks"):
        lines.extend(["### Container architecture checks", ""])
        for image, checks in report["docker_checks"].items():
            lines.append(f"- **{image}**")
            if isinstance(checks, dict):
                for tool_name, result in checks.items():
                    lines.append(f"  - `{tool_name}`: {json.dumps(result, default=str)[:300]}")
        lines.append("")

    if report.get("mca_analyses"):
        lines.extend(["### Assembly performance (LLVM-MCA)", ""])
        for path, result in report["mca_analyses"].items():
            preview = json.dumps(result, default=str)[:400]
            lines.append(f"- `{path}`: {preview}")
        lines.append("")

    if report.get("inline_suggestions"):
        lines.extend(
            [
                "### Apply-able inline suggestions",
                "",
                f"{len(report['inline_suggestions'])} suggestion(s) will be posted on the PR diff "
                "with GitHub **Apply suggestion** buttons.",
                "",
            ]
        )

    if report.get("optimization_suggestions"):
        lines.extend(["### Performance optimization suggestions", ""])
        for suggestion in report["optimization_suggestions"]:
            lines.append(f"- {suggestion}")
        lines.append("")

    if report.get("errors"):
        lines.extend(["### Analysis warnings", ""])
        for error in report["errors"]:
            lines.append(f"- {error}")

    return "\n".join(lines)


def main() -> None:
    _ensure_output_dir()
    report = asyncio.run(run_analysis())
    markdown = _render_markdown(report)
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
