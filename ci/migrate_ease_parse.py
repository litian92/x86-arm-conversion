#!/usr/bin/env python3
"""Shared migrate-ease issue parsing helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKSPACE = os.environ.get("WORKSPACE", os.getcwd())


def normalize_repo_path(filename: str) -> str:
    path = filename.strip().replace("\\", "/")
    for prefix in ("/workspace/", Path(WORKSPACE).as_posix().rstrip("/") + "/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path.lstrip("./")


def issue_type_label(issue: dict[str, Any]) -> str:
    issue_type = issue.get("issue_type")
    if isinstance(issue_type, dict):
        return str(issue_type.get("type") or issue_type.get("des") or "Issue")
    if issue_type:
        return str(issue_type)
    return "Issue"


def issue_description(issue: dict[str, Any]) -> str:
    issue_type = issue.get("issue_type")
    type_des = ""
    if isinstance(issue_type, dict):
        type_des = str(issue_type.get("des") or issue_type.get("type") or "")
    return str(issue.get("description") or type_des or "Arm migration issue detected by migrate-ease.")


def iter_migrate_ease_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for language, scan in report.get("migrate_ease_scans", {}).items():
        if not isinstance(scan, dict):
            continue
        parsed = scan.get("parsed_results")
        if isinstance(parsed, dict):
            batch = parsed.get("issues")
            if isinstance(batch, list):
                for item in batch:
                    if isinstance(item, dict):
                        enriched = dict(item)
                        enriched["_language"] = language
                        issues.append(enriched)
    return issues


def iter_issues_from_scan(scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = scan_result.get("parsed_results")
    if isinstance(parsed, dict):
        issues = parsed.get("issues")
        if isinstance(issues, list):
            return [item for item in issues if isinstance(item, dict)]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def format_finding(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)[:240]

    filename = normalize_repo_path(str(item.get("filename") or item.get("file") or item.get("path") or ""))
    lineno = item.get("lineno") or item.get("line")
    line_text = f":{lineno}" if lineno not in (None, "") else ""
    description = issue_description(item)
    type_label = issue_type_label(item)
    location = f"`{filename}{line_text}`" if filename else (f"line {lineno}" if lineno else "")

    if location and description:
        return f"{location} — {description}"
    if location:
        return location
    if description:
        return description
    return type_label
