#!/usr/bin/env python3
"""
scan_diff.py — pattern scanner for the current branch's diff.

Scans `git diff origin/develop...HEAD` for known red-flag patterns from
.coderabbit.yaml and CLAUDE.md, scoped by the layer of the file being
touched (Controller / Service / Repository / Vue / Blade).

This is a *pre-pass* for the code-reviewer skill — it gives the agent
a structured starting point of mechanical pattern matches. The agent
still has to read context and apply judgement.

Only added lines (lines starting with '+' in the unified diff) are
scanned. Pre-existing lines, even in touched files, are not flagged
unless they appear as additions.

Usage:
    python scripts/scan_diff.py
    python scripts/scan_diff.py --base origin/master
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass


# Capitalised tokens that look like Models in static-call form but aren't.
# Used to suppress false positives in the "direct Eloquent" pattern.
NON_MODEL_PREFIXES = {
    "Arr", "Artisan", "Auth", "Blade", "Bus", "Cache", "Carbon", "Config",
    "Cookie", "Crypt", "DB", "Date", "Event", "File", "Gate", "Hash",
    "Http", "JsonResponse", "Lang", "Log", "Mail", "Mockery", "Notification",
    "Number", "Password", "Pipeline", "Queue", "Redirect", "Request",
    "Response", "Route", "Rule", "Schema", "Session", "Storage", "Str",
    "URL", "Validator", "View", "AssetType", "CrmSource", "UserType",
    "Response",
}

MODEL_STATIC_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]+)::"
    r"(where|whereIn|query|find|first|firstOrFail|create|delete|update|"
    r"all|get|paginate|firstOrCreate|updateOrCreate|insert)\s*\("
)


@dataclass
class Finding:
    path: str
    line: int
    severity: str  # "MUST" or "WARN"
    rule: str
    message: str
    snippet: str


# Each rule: (severity, rule-id, compiled-regex, message, predicate?)
# predicate(match, line) -> bool; if False the finding is suppressed.
def model_predicate(m, _line):
    return m.group(1) not in NON_MODEL_PREFIXES


ALWAYS_RULES = [
    ("MUST", "no-dd-dump-die",
     re.compile(r"\b(?:dd|dump|die)\s*\("),
     "dd()/dump()/die() — forbidden in committed code", None),
    ("MUST", "no-superglobals",
     re.compile(r"\$_(?:SERVER|ENV|GET|POST|REQUEST)\b"),
     "PHP superglobal — use Laravel helpers (request(), config())", None),
    ("MUST", "raw-sql-interpolation",
     re.compile(r"->whereRaw\s*\(\s*['\"][^'\"]*\$|DB::statement\s*\(\s*['\"][^'\"]*\$"),
     "whereRaw/DB::statement with interpolated value — SQL injection risk", None),
]

CONTROLLER_RULES = [
    ("MUST", "no-direct-model",
     MODEL_STATIC_RE,
     "direct Eloquent in Controller — delegate to Repository/Service", model_predicate),
    ("MUST", "no-inline-validate",
     re.compile(r"\$request->validate\s*\("),
     "inline validation — move to a FormRequest", None),
    ("MUST", "no-inline-role",
     re.compile(r"auth\(\s*\)->user\(\s*\)->role\b"),
     "inline role check — use a Policy/Gate", None),
    ("WARN", "request-file-on-base",
     re.compile(r"\$request->(file|hasFile|allFiles)\s*\("),
     "$request->file/hasFile — ensure $request is a FormRequest with mimes:+max: rules, not the base Request", None),
]

SERVICE_RULES = [
    ("MUST", "no-request-in-service",
     re.compile(r"use\s+Illuminate\\Http\\Request\b|\bRequest\s+\$\w+"),
     "Request used inside a Service — pass plain values or DTOs", None),
    ("MUST", "no-auth-in-service",
     re.compile(r"\bAuth::|^\s*.*\bauth\(\s*\)->"),
     "Auth facade / auth() used in Service — pass the user as a parameter", None),
    ("MUST", "no-response-in-service",
     re.compile(r"\b(?:redirect|response)\s*\("),
     "redirect()/response() in Service — belongs in Controller", None),
    ("MUST", "no-direct-model",
     MODEL_STATIC_RE,
     "direct Eloquent in Service — use a Repository", model_predicate),
]

REPOSITORY_RULES = [
    ("MUST", "no-http-in-repo",
     re.compile(r"\bAuth::|\bauth\(\s*\)->|\b(?:redirect|response|session)\s*\("),
     "HTTP concern (Auth/redirect/response/session) in Repository", None),
]

VUE_RULES = [
    ("WARN", "no-console-log",
     re.compile(r"\bconsole\.(?:log|debug)\s*\("),
     "console.log/debug in committed code", None),
    ("WARN", "no-debugger",
     re.compile(r"\bdebugger\s*[;\n]"),
     "debugger statement in committed code", None),
    ("WARN", "v-html",
     re.compile(r"\bv-html\s*="),
     "v-html — XSS risk unless the value is sanitised", None),
    ("WARN", "direct-store-mutate",
     re.compile(r"\$store\.state\.[A-Za-z_][\w.]*\s*="),
     "direct Vuex state mutation — dispatch an action / commit a mutation", None),
]

BLADE_RULES = [
    ("MUST", "no-unescaped-output",
     re.compile(r"\{!!\s*\$"),
     "unescaped Blade output — XSS risk if value comes from user input", None),
    ("MUST", "no-env-in-blade",
     re.compile(r"\benv\s*\("),
     "env() in Blade — returns null when config is cached, use config()", None),
]

# Repo-wide PHP type checks: function signature without a return type.
TYPE_RULES = [
    ("MUST", "missing-return-type",
     re.compile(r"^\s*(?:public|protected|private)\s+(?:static\s+)?function\s+\w+\s*\([^)]*\)\s*\{"),
     "method signature missing return type — see .coderabbit.yaml Type declarations", None),
]


def select_rules(path: str):
    rules = list(ALWAYS_RULES)
    if path.endswith(".php"):
        rules += TYPE_RULES
        if "/Http/Controllers/" in path:
            rules += CONTROLLER_RULES
        elif "/Services/" in path:
            rules += SERVICE_RULES
        elif "/Repositories/" in path:
            rules += REPOSITORY_RULES
    if path.endswith(".vue"):
        rules += VUE_RULES
    if path.endswith(".blade.php"):
        rules += BLADE_RULES
    return rules


def parse_diff(diff_text: str):
    """Yield (path, new_line_no, line_content) for every added line."""
    path = None
    new_line_no = 0
    in_hunk = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = None
            in_hunk = False
            continue
        if raw.startswith("+++ b/"):
            path = raw[6:]
            continue
        if raw.startswith("+++ "):
            path = None
            continue
        if raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            if m:
                new_line_no = int(m.group(1)) - 1
                in_hunk = True
            continue
        if not in_hunk or path is None:
            continue
        if raw.startswith("+++"):
            continue
        if raw.startswith("+"):
            new_line_no += 1
            yield (path, new_line_no, raw[1:])
        elif raw.startswith("-"):
            pass
        elif raw.startswith(" ") or raw == "":
            new_line_no += 1


def scan(base_ref: str):
    cmd = ["git", "diff", f"{base_ref}...HEAD"]
    try:
        diff = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"error: {' '.join(cmd)} failed:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)

    findings: list[Finding] = []
    for path, lineno, content in parse_diff(diff):
        if any(s in path for s in ("vendor/", "storage/", "node_modules/")):
            continue
        for severity, rule_id, pattern, message, predicate in select_rules(path):
            m = pattern.search(content)
            if not m:
                continue
            if predicate and not predicate(m, content):
                continue
            findings.append(Finding(
                path=path, line=lineno, severity=severity, rule=rule_id,
                message=message, snippet=content.strip()[:160],
            ))
    return findings


def render(findings, show_snippets: bool):
    if not findings:
        print("No pattern matches in the diff.")
        return

    by_path: dict[str, list[Finding]] = {}
    for f in findings:
        by_path.setdefault(f.path, []).append(f)

    for path in sorted(by_path):
        print(f"\n{path}")
        for f in sorted(by_path[path], key=lambda x: (x.line, x.rule)):
            tag = f"[{f.severity:4}]"
            print(f"  +{f.line:<5} {tag} {f.rule}: {f.message}")
            if show_snippets:
                print(f"          | {f.snippet}")

    counts = {"MUST": 0, "WARN": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    print()
    print(f"Total: {counts['MUST']} MUST FIX, {counts['WARN']} WARN")


def main():
    parser = argparse.ArgumentParser(
        description="Scan branch diff for .coderabbit.yaml red flags."
    )
    parser.add_argument("--base", default="origin/develop",
                        help="Base ref to diff against (default: origin/develop)")
    parser.add_argument("--no-snippets", action="store_true",
                        help="Hide the code snippet under each finding")
    args = parser.parse_args()

    findings = scan(args.base)
    render(findings, show_snippets=not args.no_snippets)


if __name__ == "__main__":
    main()
