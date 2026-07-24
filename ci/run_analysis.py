#!/usr/bin/env python3
"""Run Arm MCP Server tools and produce a CI analysis report."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arm_mcp_client import arm_mcp_session, call_tool, get_tool_names
from performix_targets import load_performix_targets, performix_configured

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", os.getcwd())
SCAN_ROOT = os.environ.get("ARM_MCP_SCAN_ROOT", "code").strip() or "code"
WORKSPACE = os.environ.get(
    "WORKSPACE",
    str((Path(WORKSPACE_ROOT) / SCAN_ROOT).resolve())
    if SCAN_ROOT not in {".", "./"}
    else WORKSPACE_ROOT,
)
LANGUAGES = json.loads(os.environ.get("LANGUAGES", "[]"))
OPTIMIZATION_QUERIES = [
    "Arm64 performance optimization best practices",
    "x86 to Arm64 intrinsic migration",
    "NEON SIMD optimization for Arm",
    "Java performance tuning on Arm Neoverse",
]
PERFORMIX_RECIPE = os.environ.get("ARM_MCP_APX_RECIPE", "code_hotspots")


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


def _format_finding(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)[:240]

    issue_type = item.get("issue_type")
    type_label = ""
    if isinstance(issue_type, dict):
        type_label = str(issue_type.get("type") or issue_type.get("des") or "")
    elif issue_type:
        type_label = str(issue_type)

    filename = str(
        item.get("filename") or item.get("file") or item.get("path") or ""
    ).strip()
    for prefix in ("/workspace/", WORKSPACE.rstrip("/") + "/"):
        if filename.startswith(prefix):
            filename = filename[len(prefix) :]
            break
    lineno = item.get("lineno") or item.get("line")
    line_text = f":{lineno}" if lineno not in (None, "") else ""
    description = str(
        item.get("description")
        or item.get("message")
        or item.get("rule")
        or type_label
        or ""
    ).strip()

    location = f"`{filename}{line_text}`" if filename else (f"line {lineno}" if lineno else "")
    if location and description:
        return f"{location} — {description}"
    if location:
        return location
    if description:
        return description
    if type_label:
        return type_label
    return json.dumps(item)[:240]


def _iter_findings(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("issues", "findings", "results", "matches"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_finding_summaries(scan_result: dict[str, Any], limit: int = 10) -> list[str]:
    parsed = scan_result.get("parsed_results")
    summaries: list[str] = []
    for item in _iter_findings(parsed):
        if len(summaries) >= limit:
            break
        summaries.append(_format_finding(item))
    return summaries


async def run_analysis() -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": WORKSPACE,
        "scan_root": SCAN_ROOT,
        "tools_available": [],
        "migrate_ease_scans": {},
        "performix_analyses": {},
        "knowledge_base": [],
        "optimization_suggestions": [],
        "errors": [],
    }
    performix_manifest = load_performix_targets()
    report["performix_build"] = performix_manifest

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
                        "invocation_reason": (
                            f"CI scan for {language} Arm compatibility under {SCAN_ROOT}/"
                        ),
                    },
                )
                report["migrate_ease_scans"][language] = scan
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"migrate_ease_scan({language}): {exc}")

        for query in OPTIMIZATION_QUERIES:
            try:
                results = await call_tool(
                    session,
                    "knowledge_base_search",
                    {
                        "query": query,
                        "invocation_reason": (
                            f"CI performance optimization guidance for code under {SCAN_ROOT}/"
                        ),
                    },
                )
                report["knowledge_base"].append({"query": query, "results": results})
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"knowledge_base_search({query}): {exc}")

        if performix_configured() and "apx_recipe_run" in report["tools_available"]:
            recipe = str(performix_manifest.get("recipe") or PERFORMIX_RECIPE)
            remote_ip = os.environ["ARM_MCP_APX_REMOTE_IP"].strip()
            remote_user = os.environ["ARM_MCP_APX_REMOTE_USER"].strip()
            for build_error in performix_manifest.get("errors") or []:
                report["errors"].append(f"performix prepare: {build_error}")
            if performix_manifest.get("skipped"):
                report["errors"].append(f"performix: {performix_manifest['skipped']}")

            for target in performix_manifest.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                if str(target.get("language") or "").lower() not in {"", "java"}:
                    continue
                label = str(target.get("label") or target.get("id") or "java-target")
                cmd = str(target.get("cmd") or "").strip()
                if not cmd:
                    report["errors"].append(f"apx_recipe_run({label}): missing cmd")
                    continue
                try:
                    report["performix_analyses"][label] = await call_tool(
                        session,
                        "apx_recipe_run",
                        {
                            "cmd": cmd,
                            "remote_ip_addr": remote_ip,
                            "remote_usr": remote_user,
                            "recipe": recipe,
                            "invocation_reason": (
                                f"CI Performix {recipe} profiling for Java workload {label}"
                            ),
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"apx_recipe_run({label}): {exc}")

    report["optimization_suggestions"] = _build_optimization_suggestions(report)
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

    if report.get("performix_analyses"):
        suggestions.append(
            f"Review Performix `{PERFORMIX_RECIPE}` hotspots in the section above and prioritize the top sample consumers."
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
        f"Scan root: `{report.get('scan_root', SCAN_ROOT)}`",
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

    if report.get("performix_analyses"):
        lines.extend([f"### Performix ({PERFORMIX_RECIPE}) — Java only", ""])
        for target, result in report["performix_analyses"].items():
            if not isinstance(result, dict):
                lines.append(f"- `{target}`: {result}")
                continue
            status = result.get("status", "unknown")
            lines.append(f"- **`{target}`**: {status}")
            rows = result.get("rows") or []
            if isinstance(rows, list):
                for row in rows[:5]:
                    if not isinstance(row, dict):
                        continue
                    function_name = row.get("FUNCTION_NAME") or row.get("function_name") or "unknown"
                    pct = row.get("SAMPLE_PCT") or row.get("PERIODIC_SAMPLES_SELF_PERCENT")
                    times = row.get("PERIODIC_SAMPLES_SELF")
                    times_text = f" — {times} times" if times not in (None, "") else ""
                    sample_text = f" — {float(pct):.2f}% samples" if pct not in (None, "") else ""
                    lines.append(f"  - `{function_name}`{times_text}{sample_text}")
            summary = result.get("summary") or result.get("message")
            if summary:
                lines.append(f"  - {str(summary)[:300]}")
        lines.append("")

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
