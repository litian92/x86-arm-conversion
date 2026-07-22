#!/usr/bin/env python3
"""Create or update a pull-request comment with Arm MCP analysis results."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
MARKER = "<!-- arm-mcp-ci -->"
COMMENT_TITLE = "## Arm MCP Analysis Report"


def _read_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


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


def _load_report() -> dict:
    report_path = OUTPUT_DIR / "report.json"
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def _compose_comment() -> str:
    analysis_md = _read_text(OUTPUT_DIR / "report.md")
    report = _load_report()
    suggestion_count = len(report.get("optimization_suggestions", []))
    analysis_result = os.environ.get("ANALYSIS_RESULT", "unknown")

    if analysis_result == "success" and not report.get("errors"):
        overall = "pass"
    elif analysis_result == "failure":
        overall = "failed"
    else:
        overall = "needs attention"

    sections = [
        MARKER,
        COMMENT_TITLE,
        "",
        f"**Overall:** {overall}",
        "",
    ]

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

    analysis_result = os.environ.get("ANALYSIS_RESULT", "unknown")
    report = _load_report()
    if analysis_result == "failure" or report.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        raise SystemExit(1) from exc
