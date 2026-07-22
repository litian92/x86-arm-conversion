#!/usr/bin/env python3
"""Post Arm MCP summary and apply-able inline PR review suggestions."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUTPUT_DIR = Path(os.environ.get("CI_OUTPUT_DIR", "ci-output"))
MARKER = "<!-- arm-mcp-ci -->"
COMMENT_TITLE = "## Arm MCP Analysis Report"
REVIEW_MARKER = "<!-- arm-mcp-review -->"
SUGGESTION_MARKER = "<!-- arm-mcp-suggestion:"


def _read_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
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


def _load_report() -> dict:
    report_path = OUTPUT_DIR / "report.json"
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def _find_existing_issue_comment(repo: str, pr_number: str, token: str) -> int | None:
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    comments = _github_request("GET", url, token)
    for comment in comments:
        if MARKER in comment.get("body", ""):
            return comment["id"]
    return None


def _compose_summary_comment(report: dict) -> str:
    analysis_md = _read_text(OUTPUT_DIR / "report.md")
    inline_count = len(report.get("inline_suggestions", []))
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

    if inline_count:
        sections.extend(
            [
                f"**{inline_count} inline suggestion(s)** were posted on changed files.",
                "Open the **Files changed** tab and use **Apply suggestion** on each comment.",
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
            f"_Powered by [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server) "
            f"(`armlimited/arm-mcp`). {inline_count} apply-able suggestion(s), "
            f"{suggestion_count} optimization note(s)._",
        ]
    )
    return "\n".join(sections)


def _get_pull_request(repo: str, pr_number: str, token: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    result = _github_request("GET", url, token)
    return result if isinstance(result, dict) else {}


def _list_review_comments(repo: str, pr_number: str, token: str) -> list[dict]:
    comments: list[dict] = []
    page = 1
    while page <= 10:
        url = (
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
            f"?per_page=100&page={page}"
        )
        batch = _github_request("GET", url, token)
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


def _delete_review_comment(repo: str, comment_id: int, token: str) -> None:
    url = f"https://api.github.com/repos/{repo}/pulls/comments/{comment_id}"
    _github_request("DELETE", url, token)


def _cleanup_previous_suggestions(repo: str, pr_number: str, token: str) -> None:
    for comment in _list_review_comments(repo, pr_number, token):
        body = comment.get("body", "")
        if SUGGESTION_MARKER in body:
            _delete_review_comment(repo, comment["id"], token)
            print(f"Deleted previous inline suggestion comment {comment['id']}")


def _post_inline_suggestions(
    repo: str,
    pr_number: str,
    token: str,
    commit_id: str,
    suggestions: list[dict],
) -> tuple[int, list[str]]:
    if not suggestions:
        return 0, []

    posted = 0
    failures: list[str] = []

    for item in suggestions:
        payload = {
            "body": item["body"],
            "commit_id": commit_id,
            "path": item["path"],
            "line": item["line"],
            "side": "RIGHT",
        }
        start_line = item.get("start_line")
        if isinstance(start_line, int) and start_line > 0 and start_line < item["line"]:
            payload["start_line"] = start_line
            payload["start_side"] = "RIGHT"

        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
        try:
            _github_request("POST", url, token, payload)
            posted += 1
            print(f"Posted inline suggestion on {item['path']}:{item['line']}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            failures.append(f"{item['path']}:{item['line']} — {detail[:240]}")
            print(f"Failed inline suggestion on {item['path']}:{item['line']}: {detail}", file=sys.stderr)

    if posted:
        review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        summary = (
            f"{REVIEW_MARKER}\n"
            f"Posted **{posted}** Arm MCP inline suggestion(s). "
            f"Open **Files changed** and click **Apply suggestion** on each comment."
        )
        if failures:
            summary += f"\n\n{len(failures)} suggestion(s) could not be anchored to the PR diff."
        try:
            _github_request(
                "POST",
                review_url,
                token,
                {"commit_id": commit_id, "body": summary, "event": "COMMENT"},
            )
        except urllib.error.HTTPError as exc:
            print(f"Review summary note failed: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)

    return posted, failures


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")

    if not token or not repo or not pr_number:
        print("Missing GITHUB_TOKEN, GITHUB_REPOSITORY, or PR_NUMBER; skipping comment.")
        return 0

    report = _load_report()
    body = _compose_summary_comment(report)

    existing_id = _find_existing_issue_comment(repo, pr_number, token)
    if existing_id:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        _github_request("PATCH", url, token, {"body": body})
        print(f"Updated summary comment {existing_id}")
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment = _github_request("POST", url, token, {"body": body})
        if isinstance(comment, dict):
            print(f"Created summary comment {comment.get('id')}")

    inline_suggestions = report.get("inline_suggestions", [])
    if inline_suggestions:
        pull = _get_pull_request(repo, pr_number, token)
        commit_id = pull.get("head", {}).get("sha")
        if not commit_id:
            print("Could not resolve PR head commit; skipping inline suggestions.", file=sys.stderr)
        else:
            _cleanup_previous_suggestions(repo, pr_number, token)
            posted, failures = _post_inline_suggestions(
                repo, pr_number, token, commit_id, inline_suggestions
            )
            print(f"Posted {posted}/{len(inline_suggestions)} inline suggestions")
            if failures:
                for failure in failures[:5]:
                    print(f"  skipped: {failure}", file=sys.stderr)

    analysis_result = os.environ.get("ANALYSIS_RESULT", "unknown")
    if analysis_result == "failure" or report.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        raise SystemExit(1) from exc
