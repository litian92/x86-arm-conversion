#!/usr/bin/env python3
"""Create or update a pull-request comment with cross-arch build and Arm MCP results."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
MARKER = "<!-- arm-mcp-ci -->"
COMMENT_TITLE = "## Arm MCP Cross-Architecture CI Report"


def _read_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _build_status_from_log(log_path: Path) -> tuple[str, str]:
    status_path = log_path.with_name(log_path.name.replace(".log", ".json").replace("build-", "build-status-"))
    if status_path.exists():
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        status = payload.get("status", "unknown")
        exit_code = payload.get("exit_code")
        note = f"exit code {exit_code}" if exit_code is not None else "see log"
        return status, note

    content = _read_text(log_path)
    if not content:
        return "skipped", "No build log found"
    if re.search(r"\[build\].*Running:", content):
        if re.search(r"error:|ERROR|failed|FAILED", content, re.IGNORECASE):
            return "failure", "Build command reported errors (see log excerpt below)"
        return "success", "Build completed"
    return "failure", "Build script did not run successfully"


def _tail(text: str, lines: int = 20) -> str:
    parts = text.strip().splitlines()
    if len(parts) <= lines:
        return text.strip()
    return "\n".join(parts[-lines:])


def _github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _find_existing_comment(repo: str, pr_number: str, token: str) -> int | None:
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    comments = _github_request("GET", url, token)
    for comment in comments:
        if MARKER in comment.get("body", ""):
            return comment["id"]
    return None


def _compose_comment() -> str:
    build_logs_dir = OUTPUT_DIR / "build-logs"
    x86_log = build_logs_dir / "build-x86_64.log"
    arm_log = build_logs_dir / "build-arm64.log"

    x86_status, x86_message = _build_status_from_log(x86_log)
    arm_status, arm_message = _build_status_from_log(arm_log)

    analysis_md = _read_text(OUTPUT_DIR / "report.md")
    report_json_path = OUTPUT_DIR / "report.json"
    suggestion_count = 0
    if report_json_path.exists():
        report = json.loads(report_json_path.read_text(encoding="utf-8"))
        suggestion_count = len(report.get("optimization_suggestions", []))

    overall = "pass" if x86_status == "success" and arm_status == "success" else "needs attention"

    sections = [
        MARKER,
        COMMENT_TITLE,
        "",
        f"**Overall:** {overall}",
        "",
        "### Cross-architecture build verification",
        "",
        f"| Architecture | Runner | Status | Notes |",
        f"| --- | --- | --- | --- |",
        f"| x86_64 | `ubuntu-latest` | **{x86_status}** | {x86_message} |",
        f"| arm64 | `ubuntu-24.04-arm` | **{arm_status}** | {arm_message} |",
        "",
    ]

    if x86_status != "success" and x86_log.exists():
        sections.extend(
            [
                "<details>",
                "<summary>x86_64 build log excerpt</summary>",
                "",
                "```text",
                _tail(_read_text(x86_log)),
                "```",
                "",
                "</details>",
                "",
            ]
        )

    if arm_status != "success" and arm_log.exists():
        sections.extend(
            [
                "<details>",
                "<summary>arm64 build log excerpt</summary>",
                "",
                "```text",
                _tail(_read_text(arm_log)),
                "```",
                "",
                "</details>",
                "",
            ]
        )

    if analysis_md:
        sections.extend([analysis_md, ""])
    else:
        sections.extend(
            [
                "### Arm MCP analysis",
                "",
                "Analysis report was not generated. Check the `arm-mcp-analysis` job logs.",
                "",
            ]
        )

    sections.extend(
        [
            "---",
            f"_Powered by [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server) (`armlimited/arm-mcp`). "
            f"{suggestion_count} optimization suggestion(s) included._",
        ]
    )
    return "\n".join(sections)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")

    if not token or not repo or not pr_number:
        print("Missing GITHUB_TOKEN, GITHUB_REPOSITORY, or PR_NUMBER; skipping comment.")
        return 0

    body = _compose_comment()
    existing_id = _find_existing_comment(repo, pr_number, token)
    if existing_id:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        _github_request("PATCH", url, token, {"body": body})
        print(f"Updated PR comment {existing_id}")
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment = _github_request("POST", url, token, {"body": body})
        print(f"Created PR comment {comment.get('id')}")

    x86_log = OUTPUT_DIR / "build-logs" / "build-x86_64.log"
    arm_log = OUTPUT_DIR / "build-logs" / "build-arm64.log"
    x86_status, _ = _build_status_from_log(x86_log)
    arm_status, _ = _build_status_from_log(arm_log)
    if x86_status != "success" or arm_status != "success":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        raise SystemExit(1) from exc
