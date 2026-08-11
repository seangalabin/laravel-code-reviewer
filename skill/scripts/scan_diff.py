#!/usr/bin/env python3
"""
scan_diff.py — pattern scanner for the current branch's diff.

Scans `git diff origin/develop...HEAD` for known Laravel red-flag patterns,
scoped by the layer of the file being touched (Controller / Service /
Repository / Model / Resource / Command / Migration / Test / Vue / Blade).

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


# ─── Inline rule suppression ────────────────────────────────────────────────
#
# Developers can suppress a finding by placing one of these markers on the
# 1–2 lines immediately above the flagged line. The reason is required.
#
#   PHP / JS / Vue <script>:  // ai-review:ignore <reason>
#   Blade:                    {{-- ai-review:ignore <reason> --}}
#   Vue <template> / HTML:    <!-- ai-review:ignore <reason> -->

IGNORE_MARKER_RE = re.compile(
    r"(?://|\{\{--|<!--)\s*ai-review:ignore\s+(.+?)(?:\s*--\}\}|\s*-->|$)"
)
IGNORE_LOOKBACK = 2

# Cache file contents per scan so we don't re-read for every finding.
_FILE_CACHE: dict[str, list[str] | None] = {}


def _get_file_lines(path: str) -> list[str] | None:
    if path not in _FILE_CACHE:
        try:
            with open(path) as f:
                _FILE_CACHE[path] = f.readlines()
        except (OSError, UnicodeDecodeError):
            _FILE_CACHE[path] = None
    return _FILE_CACHE[path]


def has_ignore_marker_above(path: str, line: int) -> bool:
    """True if a valid ai-review:ignore marker with a non-empty reason
    appears on any of the IGNORE_LOOKBACK lines immediately above `line`."""
    lines = _get_file_lines(path)
    if lines is None:
        return False
    start = max(0, line - 1 - IGNORE_LOOKBACK)
    end   = max(0, line - 1)
    for i in range(start, end):
        m = IGNORE_MARKER_RE.search(lines[i])
        if m and m.group(1).strip():
            return True
    return False


# Capitalised tokens that look like Models in static-call form but aren't.
NON_MODEL_PREFIXES = {
    "Arr", "Artisan", "Auth", "Blade", "Bus", "Cache", "Carbon", "Config",
    "Cookie", "Crypt", "DB", "Date", "Event", "File", "Gate", "Hash",
    "Http", "JsonResponse", "Lang", "Log", "Mail", "Mockery", "Notification",
    "Number", "Password", "Pipeline", "Queue", "Redirect", "Request",
    "Response", "Route", "Rule", "Schema", "Session", "Storage", "Str",
    "URL", "Validator", "View", "AssetType", "CrmSource", "UserType",
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


def model_predicate(m, _line):
    return m.group(1) not in NON_MODEL_PREFIXES


# ─── Rules applied to every file ────────────────────────────────────────────

ALWAYS_RULES = [
    ("MUST", "no-dd-dump-die",
     re.compile(r"\b(?:dd|dump|die)\s*\("),
     "dd()/dump()/die() — forbidden in committed code", None),

    ("MUST", "no-superglobals",
     re.compile(r"\$_(?:SERVER|ENV|GET|POST|REQUEST)\b"),
     "PHP superglobal — use Laravel helpers (request(), config())", None),

    ("MUST", "raw-sql-interpolation",
     re.compile(r"->whereRaw\s*\(\s*['\"][^'\"]*\$|DB::statement\s*\(\s*['\"][^'\"]*\$"),
     "whereRaw/DB::statement with interpolated value — SQL injection risk; use bound parameters", None),

    ("MUST", "no-debug-output",
     re.compile(r"\b(?:error_log|var_dump|print_r)\s*\("),
     "error_log/var_dump/print_r — use Log::info/error/debug instead", None),

    ("MUST", "secret-literal",
     re.compile(
         r"AKIA[0-9A-Z]{16}"
         r"|-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY"
         r"|(?i:secret|api[_-]?key|token|passwd|password)\w*['\"]?\s*(?:=|=>|:)\s*['\"][A-Za-z0-9+/_\-]{20,}['\"]"
     ),
     "possible hardcoded secret/credential — move it to config/credential storage; rotate if already committed", None),
]

# ─── PHP-wide (all .php files) ──────────────────────────────────────────────

PHP_RULES = [
    ("MUST", "missing-return-type",
     re.compile(r"^\s*(?:public|protected|private)\s+(?:static\s+)?function\s+\w+\s*\([^)]*\)\s*$"),
     "method signature missing return type — add `: ReturnType` before the opening brace", None),

    ("MUST", "env-outside-config",
     re.compile(r"\benv\s*\("),
     "env() outside config/ — returns null when config is cached; use config() with a config key instead", None),

    ("WARN", "missing-strict-types",
     re.compile(r"^<\?php\s*$"),
     "new PHP file — confirm declare(strict_types=1) appears as first statement after <?php", None),

    ("WARN", "http-without-timeout",
     re.compile(r"\bHttp::(get|post|put|patch|delete|send|withHeaders|withToken|withBasicAuth|withBody|asForm|asJson)\s*\("),
     "Http:: call — verify ->timeout(N) is chained; without it the request can hang indefinitely", None),

    ("WARN", "select-star",
     re.compile(r"->select\s*\(\s*['\"]\*['\"]|->selectRaw\s*\(\s*['\"](?i:select\s+\*)|DB::(?:raw|select)\s*\(\s*['\"](?i:select\s+\*)"),
     "explicit select('*') — redundant; list only the columns actually used (keep id + FKs + accessor/cast sources)", None),

    ("WARN", "get-then-pluck",
     re.compile(r"->get\s*\(\s*\)\s*->pluck\s*\("),
     "->get()->pluck() loads every column then plucks — call ->pluck() on the builder instead", None),

    ("WARN", "log-getmessage",
     re.compile(r"Log::(?:error|warning|critical|info|debug|notice|alert|emergency)\s*\(\s*(?:['\"][^'\"]*['\"]\s*\.\s*)?\$\w+->getMessage\s*\("),
     "Log::*($e->getMessage()) flattens the exception and drops the trace — prefer report($e), or pass ['exception' => $e]", None),

    ("MUST", "exception-in-response",
     re.compile(r"(?:response\s*\(\s*\)->json|abort(?:_if|_unless)?)\s*\(.*->get(?:Message|TraceAsString|File|Line)\s*\("),
     "raw exception detail in an HTTP response — leaks internals to the client; return a generic message and report($e) instead", None),
]

# ─── Controllers ────────────────────────────────────────────────────────────

CONTROLLER_RULES = [
    ("MUST", "no-direct-model",
     MODEL_STATIC_RE,
     "direct Eloquent in Controller — delegate to Repository or Service", model_predicate),

    ("MUST", "no-inline-validate",
     re.compile(r"\$request->validate\s*\("),
     "inline validation — move to a dedicated FormRequest class", None),

    ("MUST", "no-inline-role",
     re.compile(r"(?:auth\(\s*\)->user\(\s*\)->role\b|\$user->role\s*===|\$request->user\(\s*\)->is_admin)"),
     "inline role/permission check — use a Policy or Gate", None),

    ("MUST", "no-raw-toarray-response",
     re.compile(r"->toArray\s*\(\s*\)|->toJson\s*\(\s*\)|response\(\s*\)->json\s*\(\s*\$\w+->toArray"),
     "raw ->toArray() / ->toJson() in controller response — use an API Resource class instead", None),

    ("MUST", "no-raw-model-json",
     re.compile(r"response\(\s*\)->json\s*\(\s*\$[a-z]\w*\s*\)"),
     "response()->json($model) — use an API Resource to control the schema", None),

    ("MUST", "no-mass-assignment-request-all",
     re.compile(r"::create\s*\(\s*\$request->all\s*\(\s*\)\s*\)|->update\s*\(\s*\$request->all\s*\(\s*\)\s*\)"),
     "mass assignment via $request->all() — use $request->safe()->only([...]) or $request->validated() with $fillable", None),

    ("WARN", "request-file-no-mimes",
     re.compile(r"\$request->(file|hasFile|allFiles)\s*\("),
     "$request->file/hasFile — confirm FormRequest has both mimes:/mimetypes: and max: on the file rule", None),

    ("WARN", "no-di-new-service",
     re.compile(r"\bnew\s+[A-Z][A-Za-z0-9]+(?:Service|Repository|Manager|Handler)\s*\("),
     "uninjected Service/Repository — use constructor injection so the container can resolve it and tests can mock it", None),
]

# ─── Services ───────────────────────────────────────────────────────────────

SERVICE_RULES = [
    ("MUST", "no-request-in-service",
     re.compile(r"use\s+Illuminate\\Http\\Request\b|\bRequest\s+\$\w+"),
     "Request in Service — pass plain values or DTOs; Services must be HTTP-agnostic", None),

    ("MUST", "no-auth-in-service",
     re.compile(r"\bAuth::|^\s*.*\bauth\(\s*\)->"),
     "Auth facade / auth() in Service — resolve the user in the Controller and pass it as a parameter", None),

    ("MUST", "no-response-in-service",
     re.compile(r"\b(?:redirect|response)\s*\("),
     "redirect()/response() in Service — HTTP response construction belongs in the Controller", None),

    ("MUST", "no-session-in-service",
     re.compile(r"\bsession\s*\("),
     "session() in Service — HTTP session access belongs in the Controller or Middleware", None),

    ("MUST", "no-direct-model",
     MODEL_STATIC_RE,
     "direct Eloquent in Service — all DB access must go through a Repository", model_predicate),

    ("WARN", "array-boundary-dto",
     re.compile(r"function\s+\w+\s*\(\s*array\s+\$\w+\s*[,)]"),
     "Service method accepts raw array — consider a typed DTO class for the cross-layer boundary", None),

    ("WARN", "synchronous-mail-in-service",
     re.compile(r"\bMail::(to|send|queue)\s*\("),
     "synchronous Mail:: in Service — consider dispatching a queued Job or firing a UserRegistered event", None),
]

# ─── Repositories ───────────────────────────────────────────────────────────

REPOSITORY_RULES = [
    ("MUST", "no-http-in-repo",
     re.compile(r"\bAuth::|\bauth\(\s*\)->|\b(?:redirect|response|session)\s*\("),
     "HTTP concern (Auth/redirect/response/session) in Repository", None),
]

# ─── Models ─────────────────────────────────────────────────────────────────

MODEL_RULES = [
    ("WARN", "empty-guarded",
     re.compile(r"\$guarded\s*=\s*\[\s*\]"),
     "$guarded = [] — use an explicit $fillable list to prevent mass-assignment of sensitive columns", None),

    ("WARN", "fill-all-request",
     re.compile(r"->(?:fill|update)\s*\(\s*\$request->all\s*\(\s*\)\s*\)"),
     "fill/update with $request->all() — explicitly whitelist fields to prevent mass assignment", None),
]

# ─── FormRequests ───────────────────────────────────────────────────────────

FORM_REQUEST_RULES = [
    ("WARN", "authorize-true",
     re.compile(r"return\s+true\s*;"),
     "authorize() returns true unconditionally — add a Policy/Gate check or acknowledge the intent", None),
]

# ─── JS / Vue ───────────────────────────────────────────────────────────────

JS_RULES = [
    ("WARN", "no-console-log",
     re.compile(r"\bconsole\.(?:log|debug)\s*\("),
     "console.log/debug in committed code", None),

    ("WARN", "no-debugger",
     re.compile(r"\bdebugger\s*[;\n]"),
     "debugger statement in committed code", None),

    ("WARN", "add-event-listener",
     re.compile(r"\baddEventListener\s*\("),
     "addEventListener — verify a matching removeEventListener exists in beforeUnmount()/destroyed() to prevent memory leaks", None),
]

VUE_RULES = JS_RULES + [
    ("MUST", "v-html",
     re.compile(r"\bv-html\s*="),
     "v-html — XSS risk if the value is not sanitised before assignment (DOMPurify or trusted internal source only)", None),

    ("MUST", "direct-store-mutate",
     re.compile(r"\$store\.state\.[A-Za-z_][\w.]*\s*="),
     "direct Vuex state mutation — use commit('mutation') so DevTools tracks the change", None),

    ("WARN", "key-is-index",
     re.compile(r":key\s*=\s*[\"']?\s*index\s*[\"']?|:key\s*=\s*\"\s*\$index\s*\""),
     ":key bound to loop index — use a stable unique ID (record.id) so Vue patches the right instances when items reorder", None),

    ("WARN", "direct-dom",
     re.compile(r"\bdocument\.(querySelector|getElementById|getElementsBy)\s*\("),
     "direct DOM manipulation in Vue — use this.$refs.name instead so Vue controls the element lifecycle", None),
]

# ─── API Resources ──────────────────────────────────────────────────────────

RESOURCE_RULES = [
    ("MUST", "resource-db-query",
     MODEL_STATIC_RE,
     "Eloquent query inside an API Resource toArray() — Resources must only transform already-loaded data; eager-load in the Repository/Controller instead", model_predicate),
    # NOTE: a "relation accessed directly in Resource" pre-pass rule was removed —
    # any `$this->x->`/`$this->x[` matched, flooding the agent with false positives.
    # The lens (§4a whenLoaded) still instructs the agent to check this by judgement.
]

# ─── Console Commands ────────────────────────────────────────────────────────

COMMAND_RULES = [
    ("MUST", "command-direct-model",
     MODEL_STATIC_RE,
     "direct Eloquent in Console Command handle() — delegate to a Repository", model_predicate),

    ("WARN", "command-business-logic",
     re.compile(r"(?:if\s*\(|foreach\s*\(|for\s*\(|while\s*\()"),
     "business logic in Console Command handle() — delegate conditionals and loops to a Service or Repository (WARN: guard clauses are fine; agent filters)", None),

    ("WARN", "command-echo-output",
     re.compile(r"\becho\s+"),
     "echo in Console Command — use $this->info() / $this->error() so output goes through Laravel's console stack", None),
]

# ─── Migrations ──────────────────────────────────────────────────────────────

MIGRATION_RULES = [
    ("WARN", "migration-model-import",
     re.compile(r"use\s+App\\Models\\[A-Z]\w+\s*;"),
     "Model class imported in migration — use DB:: or raw table names so the migration survives Model renames or deletions", None),

    ("WARN", "migration-model-reference",
     re.compile(r"\b[A-Z][A-Za-z0-9]+::(?:create|find|where|insert|update|delete|all|get)\s*\("),
     "Model static call in migration — use DB:: or raw table names so the migration survives Model renames", None),

    ("WARN", "migration-no-down",
     re.compile(r"public\s+function\s+down\s*\(\s*\)\s*$"),
     "down() method is present but may be empty — ensure rollback logic is implemented", None),
]

# ─── Tests ───────────────────────────────────────────────────────────────────

TEST_RULES = [
    ("MUST", "test-stray-http",
     re.compile(r"\bHttp::(get|post|put|patch|delete)\s*\("),
     "outbound Http:: in test without Http::fake() — add Http::fake() or fakeHttpResponse() to prevent stray requests", None),

    ("MUST", "test-reflection-private",
     re.compile(r"ReflectionClass|ReflectionMethod|setAccessible\s*\("),
     "testing private/protected method via reflection — test observable behaviour through the public API instead", None),

    ("WARN", "test-without-exception-handling",
     re.compile(r"->withoutExceptionHandling\s*\("),
     "withoutExceptionHandling() — debugging aid must not be merged", None),

    ("WARN", "test-mockery-direct",
     re.compile(r"\bMockery::mock\s*\("),
     "Mockery::mock() used directly — use mock(ClassName::class) from tests/Helpers.php so the binding resolves via the container", None),
]

# ─── Blade ──────────────────────────────────────────────────────────────────

BLADE_RULES = [
    ("MUST", "unescaped-output",
     re.compile(r"\{!!\s*\$"),
     "unescaped Blade output {!! $var !!} — XSS risk if value originates from user input", None),

    ("MUST", "env-in-blade",
     re.compile(r"\benv\s*\("),
     "env() in Blade — returns null when config is cached; use config() instead", None),
]


def select_rules(path: str):
    rules = list(ALWAYS_RULES)
    if path.endswith(".php"):
        # env() rule only for non-config files
        if not path.startswith("config/"):
            rules += PHP_RULES
        else:
            # In config files, env() is correct — skip PHP_RULES env check
            rules += [r for r in PHP_RULES if r[1] != "env-outside-config"]

        if "/Http/Controllers/" in path:
            rules += CONTROLLER_RULES
        elif "/Services/" in path:
            rules += SERVICE_RULES
        elif "/Repositories/" in path:
            rules += REPOSITORY_RULES
        elif "/Models/" in path:
            rules += MODEL_RULES
        elif "/Http/Requests/" in path:
            rules += FORM_REQUEST_RULES
        elif "/Http/Resources/" in path:
            rules += RESOURCE_RULES
        elif "/Console/Commands/" in path:
            rules += COMMAND_RULES
        elif path.startswith("database/migrations/"):
            rules += MIGRATION_RULES
        elif path.startswith("tests/"):
            rules += TEST_RULES

    if path.endswith((".js", ".jsx", ".ts", ".tsx")):
        rules += JS_RULES

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


def scan_text(diff_text: str):
    """Pure scanner over a unified-diff string — no git, no exit()."""
    findings: list[Finding] = []
    for path, lineno, content in parse_diff(diff_text):
        if any(s in path for s in ("vendor/", "storage/", "node_modules/")):
            continue
        if has_ignore_marker_above(path, lineno):
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


def build_diff_cmd(base_ref: str, files: list[str] | None = None) -> list[str]:
    """git-diff invocation, optionally scoped to a file list (checkpoint mode
    with merges in range: restrict to branch-own files)."""
    cmd = ["git", "diff", f"{base_ref}...HEAD"]
    if files:
        cmd.append("--")
        cmd.extend(files)
    return cmd


def scan(base_ref: str, files: list[str] | None = None):
    cmd = build_diff_cmd(base_ref, files)
    try:
        diff = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"error: {' '.join(cmd)} failed:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    return scan_text(diff)


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

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    print()
    print(f"Total: {counts.get('MUST', 0)} MUST FIX, {counts.get('WARN', 0)} WARN")


def main():
    parser = argparse.ArgumentParser(
        description="Scan branch diff for Laravel layering, security, and quality red flags."
    )
    parser.add_argument("--base", default="origin/develop",
                        help="Base ref to diff against (default: origin/develop)")
    parser.add_argument("--files", nargs="+", default=None, metavar="PATH",
                        help="Restrict the scan to these paths (checkpoint mode with "
                             "merges in range: pass the branch-own file list)")
    parser.add_argument("--no-snippets", action="store_true",
                        help="Hide the code snippet under each finding")
    args = parser.parse_args()

    findings = scan(args.base, args.files)
    render(findings, show_snippets=not args.no_snippets)


if __name__ == "__main__":
    main()
