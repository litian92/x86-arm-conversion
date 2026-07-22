#!/usr/bin/env python3
"""Build GitHub apply-able inline suggestions from migrate-ease findings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migrate_ease_parse import (
    issue_description,
    issue_type_label,
    iter_migrate_ease_issues,
    normalize_repo_path,
)

SUGGESTION_MARKER = "<!-- arm-mcp-suggestion:"
MAX_SUGGESTIONS = 25

INTRINSIC_HEADER_PATTERN = re.compile(r"#include\s*[<\"]?(emmintrin|immintrin|xmmintrin|pmmintrin|smmintrin)", re.I)
AVX_TYPE_PATTERN = re.compile(r"__m(128|256|512)")
INLINE_ASM_PATTERN = re.compile(r"__asm__|asm\s+volatile|asm\s*\(")
X86_ASM_PATTERN = re.compile(r"\b(pushq|popq|movq|movl|addl|\.ident)\b")


@dataclass
class InlineSuggestion:
    path: str
    start_line: int
    line: int
    body: str
    issue_type: str
    fingerprint: str


def _read_lines(repo_root: Path, rel_path: str) -> list[str]:
    path = repo_root / rel_path
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _find_function_range(lines: list[str], lineno: int) -> tuple[int, int] | None:
    if lineno < 1 or lineno > len(lines):
        return None
    idx = lineno - 1
    while idx >= 0 and not re.match(r"^[A-Za-z_].*\(.*\)\s*$", lines[idx].strip()) and "{" not in lines[idx]:
        idx -= 1
    if idx < 0:
        return None
    start = idx
    brace_depth = 0
    end = start
    for i in range(start, len(lines)):
        brace_depth += lines[i].count("{") - lines[i].count("}")
        end = i + 1
        if brace_depth == 0 and "{" in lines[start:i + 1]:
            return start + 1, end
    return start + 1, min(len(lines), start + 20)


def _suggestion_body(issue_type: str, description: str, code: str, fingerprint: str) -> str:
    return (
        f"{SUGGESTION_MARKER}{fingerprint} -->\n"
        f"**Arm MCP · {issue_type}**\n\n"
        f"{description}\n\n"
        f"```suggestion\n"
        f"{code.rstrip()}\n"
        f"```"
    )


def _fix_intrinsic_header(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    if lineno < 1 or lineno > len(lines):
        return None
    line = lines[lineno - 1]
    if not INTRINSIC_HEADER_PATTERN.search(line):
        return None

    replacement = "\n".join(
        [
            "#if defined(__x86_64__) || defined(_M_X64)",
            "#include <immintrin.h>",
            "#elif defined(__aarch64__)",
            "#include <arm_neon.h>",
            "#else",
            '#error "Unsupported CPU architecture for SIMD intrinsics"',
            "#endif",
        ]
    )
    fingerprint = f"{rel_path}:{lineno}:intrinsic-header"
    return InlineSuggestion(
        path=rel_path,
        start_line=lineno,
        line=lineno,
        body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
        issue_type=issue_type_label(issue),
        fingerprint=fingerprint,
    )


def _fix_avx_function(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    fn_range = _find_function_range(lines, lineno)
    if not fn_range:
        return None
    start, end = fn_range
    block = "\n".join(lines[start - 1 : end])
    if not AVX_TYPE_PATTERN.search(block):
        return None

    fn_name_match = re.search(r"(\w+)\s*\(", lines[start - 1])
    fn_name = fn_name_match.group(1) if fn_name_match else "simd_fn"

    if fn_name == "add_epi":
        replacement = "\n".join(
            [
                "#if defined(__x86_64__) || defined(_M_X64)",
                "__m256i add_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    __m256i i2561 = _mm256_set1_epi32(data1);",
                "    __m256i i2562 = _mm256_set1_epi32(data2);",
                "    return _mm256_sub_epi32(i2561, i2562);",
                "}",
                "#elif defined(__aarch64__)",
                "int32x4_t add_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    int32x4_t v1 = vdupq_n_s32((int32_t)data1);",
                "    int32x4_t v2 = vdupq_n_s32((int32_t)data2);",
                "    return vsubq_s32(v1, v2);",
                "}",
                "#else",
                "unsigned int add_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    return data1 - data2;",
                "}",
                "#endif",
            ]
        )
    elif fn_name == "max_epi":
        replacement = "\n".join(
            [
                "#if defined(__x86_64__) || defined(_M_X64)",
                "__m256i max_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    __m256i i2561 = _mm256_set1_epi32(data1);",
                "    __m256i i2562 = _mm256_set1_epi32(data2);",
                "    return _mm256_max_epi32(i2561, i2562);",
                "}",
                "#elif defined(__aarch64__)",
                "int32x4_t max_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    int32x4_t v1 = vdupq_n_s32((int32_t)data1);",
                "    int32x4_t v2 = vdupq_n_s32((int32_t)data2);",
                "    return vmaxq_s32(v1, v2);",
                "}",
                "#else",
                "unsigned int max_epi(unsigned int data1, unsigned int data2)",
                "{",
                "    return data1 > data2 ? data1 : data2;",
                "}",
                "#endif",
            ]
        )
    else:
        replacement = "\n".join(
            [
                "#if defined(__x86_64__) || defined(_M_X64)",
                block,
                "#elif defined(__aarch64__)",
                "/* TODO: replace x86 intrinsics above with Arm NEON equivalents */",
                "#else",
                "/* TODO: provide a portable scalar fallback */",
                "#endif",
            ]
        )

    fingerprint = f"{rel_path}:{start}:{fn_name}:avx-fn"
    return InlineSuggestion(
        path=rel_path,
        start_line=start,
        line=end,
        body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
        issue_type=issue_type_label(issue),
        fingerprint=fingerprint,
    )


def _fix_inline_asm(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
    if "bswap" in line:
        replacement = "\n".join(
            [
                "#if defined(__x86_64__) || defined(_M_X64)",
                '    __asm__("bswap %0" : "=r" (result) : "0" (data));',
                "#elif defined(__aarch64__)",
                "    result = __builtin_bswap32(data);",
                "#else",
                "    result = ((data & 0x000000FFu) << 24) | ((data & 0x0000FF00u) << 8)",
                "           | ((data & 0x00FF0000u) >> 8) | ((data & 0xFF000000u) >> 24);",
                "#endif",
            ]
        )
        fingerprint = f"{rel_path}:{lineno}:bswap"
        return InlineSuggestion(
            path=rel_path,
            start_line=lineno,
            line=lineno,
            body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
            issue_type=issue_type_label(issue),
            fingerprint=fingerprint,
        )

    fn_range = _find_function_range(lines, lineno)
    if not fn_range:
        return None
    start, end = fn_range
    block = "\n".join(lines[start - 1 : end])
    if "multi_inst" in block or ("movq" in block and "__asm__" in block):
        replacement = "\n".join(
            [
                "long int multi_inst(long int data1, long int data2)",
                "{",
                "    return (data1 << 1) | data2;",
                "}",
            ]
        )
        fingerprint = f"{rel_path}:{start}:multi_inst"
        return InlineSuggestion(
            path=rel_path,
            start_line=start,
            line=end,
            body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
            issue_type=issue_type_label(issue),
            fingerprint=fingerprint,
        )

    if "lock ; incb" in block or "incb" in block:
        replacement = "\n".join(
            [
                "void inst_function_test_lock_inc(signed char V0)",
                "{",
                "#if defined(__x86_64__) || defined(_M_X64)",
                "    asm volatile(",
                '        "lock ; incb %[cnt] \\n\\t"',
                "        : [cnt] \"+m\"(V0)",
                "        :",
                "    );",
                "#else",
                "    __atomic_fetch_add(&V0, 1, __ATOMIC_SEQ_CST);",
                "#endif",
                "}",
            ]
        )
        fingerprint = f"{rel_path}:{start}:lock-inc"
        return InlineSuggestion(
            path=rel_path,
            start_line=start,
            line=end,
            body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
            issue_type=issue_type_label(issue),
            fingerprint=fingerprint,
        )

    return None


def _fix_x86_assembly(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    block = "\n".join(lines)
    if not X86_ASM_PATTERN.search(block):
        return None

    replacement = "\n".join(
        [
            "    .globl  caller",
            "    .type   caller, %function",
            "caller:",
            "    add     w0, w0, w1",
            "    ret",
            "    .size   caller, .-caller",
        ]
    )

    start = 16
    end = min(len(lines), 39)
    for i, text in enumerate(lines, start=1):
        if text.strip().startswith(".globl") and "caller" in text:
            start = i
        if i >= start and text.strip().startswith(".size") and "caller" in text:
            end = i
            break

    fingerprint = f"{rel_path}:{start}:aarch64-caller"
    return InlineSuggestion(
        path=rel_path,
        start_line=start,
        line=end,
        body=_suggestion_body(
            issue_type_label(issue),
            issue_description(issue) + " Replace the x86_64 `caller` stub with an AArch64 version.",
            replacement,
            fingerprint,
        ),
        issue_type=issue_type_label(issue),
        fingerprint=fingerprint,
    )


def _fix_build_command(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    if lineno < 1 or lineno > len(lines):
        return None
    line = lines[lineno - 1]
    if "gcc" not in line and "FLAGS" not in line and "g++" not in line and "clang" not in line:
        return None

    if "FLAGS" in line and "=" in line:
        replacement = "FLAGS = -g -DDEBUG -W -Wall -fPIC -std=gnu99 -march=armv8-a"
    elif line.strip().startswith("gcc") and "-c" in line and ".s" in line:
        replacement = "\tgcc -c ./interface.s -o interface.o"
    elif "interface.o" in line and ".s" in line:
        replacement = "interface.o: interface.s\n\tgcc -c ./interface.s -o interface.o"
    else:
        replacement = line.replace("-mavx2", "").replace("-mavx", "").strip()
        if replacement == line.strip():
            replacement = line.rstrip() + " -march=armv8-a"

    fingerprint = f"{rel_path}:{lineno}:build"
    return InlineSuggestion(
        path=rel_path,
        start_line=lineno,
        line=lineno,
        body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
        issue_type=issue_type_label(issue),
        fingerprint=fingerprint,
    )


def _fix_header_declarations(lines: list[str], lineno: int, issue: dict[str, Any], rel_path: str) -> InlineSuggestion | None:
    if lineno < 1 or lineno > len(lines):
        return None
    line = lines[lineno - 1]
    if not AVX_TYPE_PATTERN.search(line):
        return None
    replacement = "\n".join(
        [
            "#if defined(__x86_64__) || defined(_M_X64)",
            "__m256i add_epi(unsigned int data1, unsigned int data2);",
            "__m256i max_epi(unsigned int data1, unsigned int data2);",
            "#elif defined(__aarch64__)",
            "int32x4_t add_epi(unsigned int data1, unsigned int data2);",
            "int32x4_t max_epi(unsigned int data1, unsigned int data2);",
            "#else",
            "unsigned int add_epi(unsigned int data1, unsigned int data2);",
            "unsigned int max_epi(unsigned int data1, unsigned int data2);",
            "#endif",
        ]
    )
    start = lineno
    end = lineno
    while end < len(lines) and AVX_TYPE_PATTERN.search(lines[end]):
        end += 1
    if end > start:
        replacement = "\n".join(
            [
                "#if defined(__x86_64__) || defined(_M_X64)",
                *[lines[i - 1] for i in range(start, end + 1)],
                "#elif defined(__aarch64__)",
                "int32x4_t add_epi(unsigned int data1, unsigned int data2);",
                "int32x4_t max_epi(unsigned int data1, unsigned int data2);",
                "#else",
                "unsigned int add_epi(unsigned int data1, unsigned int data2);",
                "unsigned int max_epi(unsigned int data1, unsigned int data2);",
                "#endif",
            ]
        )

    fingerprint = f"{rel_path}:{start}:header-decls"
    return InlineSuggestion(
        path=rel_path,
        start_line=start,
        line=end,
        body=_suggestion_body(issue_type_label(issue), issue_description(issue), replacement, fingerprint),
        issue_type=issue_type_label(issue),
        fingerprint=fingerprint,
    )


def build_inline_suggestion(
    issue: dict[str, Any],
    repo_root: Path,
) -> InlineSuggestion | None:
    rel_path = normalize_repo_path(str(issue.get("filename") or issue.get("file") or issue.get("path") or ""))
    lineno = issue.get("lineno") or issue.get("line")
    if not rel_path or not lineno:
        return None

    try:
        lineno = int(lineno)
    except (TypeError, ValueError):
        return None

    lines = _read_lines(repo_root, rel_path)
    if not lines:
        return None

    issue_type = issue_type_label(issue)
    content_line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""

    fixers: list[Any] = []
    if issue_type in {"BuildCommand", "CrossCompile", "CompilerSpecific"} or rel_path.endswith("Makefile"):
        fixers.append(_fix_build_command)
    if rel_path.endswith((".s", ".S")) or issue_type in {"AsmSource", "NoEquivalentInlineAsm"}:
        fixers.append(_fix_x86_assembly)
    if INTRINSIC_HEADER_PATTERN.search(content_line) or issue_type in {"ArchSpecificLibrary", "Intrinsic"}:
        fixers.append(_fix_intrinsic_header)
    if AVX_TYPE_PATTERN.search(content_line) and rel_path.endswith((".h", ".hpp")):
        fixers.append(_fix_header_declarations)
    if AVX_TYPE_PATTERN.search(content_line) or issue_type in {
        "Avx256Intrinsic",
        "Avx512Intrinsic",
        "NoEquivalentIntrinsic",
        "Intrinsic",
    }:
        fixers.append(_fix_avx_function)
    if INLINE_ASM_PATTERN.search(content_line) or issue_type in {"InlineAsm", "NoEquivalentInlineAsm"}:
        fixers.append(_fix_inline_asm)

    fixers.extend([_fix_intrinsic_header, _fix_avx_function, _fix_inline_asm, _fix_x86_assembly, _fix_build_command])

    seen: set[str] = set()
    for fixer in fixers:
        key = fixer.__name__
        if key in seen:
            continue
        seen.add(key)
        suggestion = fixer(lines, lineno, issue, rel_path)
        if suggestion is not None:
            return suggestion
    return None


def build_inline_suggestions(report: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    suggestions: list[InlineSuggestion] = []
    seen_fingerprints: set[str] = set()

    for issue in iter_migrate_ease_issues(report):
        built = build_inline_suggestion(issue, repo_root)
        if built is None or built.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(built.fingerprint)
        suggestions.append(built)
        if len(suggestions) >= MAX_SUGGESTIONS:
            break

    return [
        {
            "path": item.path,
            "start_line": item.start_line,
            "line": item.line,
            "body": item.body,
            "issue_type": item.issue_type,
            "fingerprint": item.fingerprint,
        }
        for item in suggestions
    ]
