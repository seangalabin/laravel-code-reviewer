# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects and posts inline comments directly to the PR.

For developers who want to fix issues on their own branch before pushing (instead of posting to a PR), use the companion skill [`code-fixer`](#code-fixer-developer-skill).

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Refuse to run on `main`, `master`, or `develop` (feature branches only)
2. Check previously posted comments — mark any that have been addressed, and respond to developer replies on them
3. Refresh dismissal memory — skip findings a developer has already marked won't-fix
4. Diff the current branch against `develop`
5. Run a mechanical pre-pass (`scan_diff.py`) over the changed lines to surface red flags
6. Apply a 15-dimension review lens to every hunk
7. Ask: **Post {N} findings to PR #{ID}? [y/n]** — the only interactive prompt
8. Post each finding as an inline Bitbucket PR comment with a copy-pasteable fix prompt

## Review dimensions

| # | Dimension | Examples |
|---|---|---|
| 1 | Architecture & Layering | Controller→Service→Repository, DTOs, FormRequests, Console Commands |
| 2 | PSR-12 & Code Standards | `strict_types`, return types, parameter types, property types, naming |
| 3 | Security | Mass assignment, SQL injection, IDOR, inline role checks, file uploads, XSS |
| 4 | Laravel Best Practices | N+1, API Resources, Jobs/Events/Observers, DI, `DB::transaction()` |
| 5 | Models | Business logic, HTTP concerns, scopes vs own queries |
| 6 | Enums | Business logic beyond label/color helpers |
| 7 | Correctness | Null dereferences, race conditions, wrong status codes |
| 8 | Data Integrity | Multi-write transactions, check-then-act, locking |
| 9 | Performance | N+1, full-table loads, `Http::` timeout |
| 10 | Error Handling | Swallowed exceptions, missing HTTP error handling |
| 11 | Migrations | Non-null without default (table lock risk), Model refs, empty `down()` |
| 12 | Vue / JavaScript | `:key`, Vuex mutation, `v-html` XSS, event listener leaks |
| 13 | Testing | Stray HTTP, reflection, `withoutExceptionHandling()`, missing assertions |
| 14 | API Design | Status codes, pagination, Resource field exposure |
| 15 | Blade views | Business logic in views, N+1 in `@foreach`, URL/attr XSS, CSRF, dynamic `@include` |

## Severity

| | Severity | When |
|---|---|---|
| 🔴 | **Critical** | Bug, security issue, data loss risk. Creates a blocking task on the PR. |
| 🟡 | **Warning** | Likely problem, performance, maintainability. |
| 🔵 | **Suggestion** | Style, readability, minor improvement. |

Each finding contains: what's wrong in plain language, a copy-pasteable Claude Code prompt to fix it, a suggested diff, and an explanation of why the fix works.

## Requirements

- Node.js 16+
- Laravel project with [PestPHP](https://pestphp.com/) and [Laravel Pint](https://laravel.com/docs/pint)
- [Claude Code](https://claude.ai/code) CLI
- A Bitbucket repository with an open PR on the current branch
- **Shell:** Linux, macOS, or WSL/Git Bash run the `.sh` scripts. On native **Windows**, `code-reviewer` runs PowerShell (`pwsh` 7+, or Windows PowerShell 5.1) variants and additionally needs **Python 3** and **curl** on `PATH` (curl ships with Windows 10 1803+). The skill auto-detects the OS and runs the matching `.sh`/`.ps1` scripts.

## Installation

```bash
npx github:seangalabin/laravel-code-reviewer
```

To install into a specific directory:

```bash
npx github:seangalabin/laravel-code-reviewer /path/to/project
```

The installer copies the skill files into `.claude/skills/code-reviewer/` and writes `allowedTools` entries to `.claude/settings.json` so the review scripts run without per-command confirmation prompts.

## Setup

After installing, add your Bitbucket credentials to `.claude/settings.local.json` in the project root (gitignored — each developer does this once):

```json
{
  "env": {
    "BITBUCKET_EMAIL": "your@email.com",
    "BITBUCKET_API_TOKEN": "your_api_token"
  }
}
```

Create a Bitbucket API token with **Pull requests: write** scope at:
https://bitbucket.org/account/settings/personal-access-tokens/

### Optional — Jira card status sync

To automatically transition the linked Jira card after each review (`Failed Code Review` when findings remain, `Code Review` when clean / all-addressed), also add to `.claude/settings.local.json`:

```json
{
  "env": {
    "JIRA_BASE_URL":     "https://yourcompany.atlassian.net",
    "JIRA_EMAIL":        "your@email.com",
    "JIRA_API_TOKEN":    "your_jira_api_token"
  }
}
```

`JIRA_EMAIL` and `JIRA_API_TOKEN` fall back to `BITBUCKET_EMAIL` / `BITBUCKET_API_TOKEN` if your Bitbucket and Jira accounts share an Atlassian login — set the dedicated ones only when they differ.

Override the status names if your workflow uses different labels:

```json
{
  "env": {
    "JIRA_FAILED_STATUS": "Failed Code Review",
    "JIRA_PASSED_STATUS": "Code Review"
  }
}
```

If any Jira variable is missing the sync soft-skips — the review itself never fails.

Restart Claude Code to pick up any new environment variables.

## Usage

Open Claude Code in your Laravel project and run:

```
/code-reviewer
```

The skill auto-detects the current branch, finds the open PR, runs the analysis, then asks before posting:

```
/code-reviewer
> Found 5 issues (1 critical, 3 warnings, 1 suggestion) on branch feature/payments.
> Post to PR #42? [y/n]
y
> Posted 5 comments to PR #42. Review them at https://bitbucket.org/...
```

### Inline suppression

Add a marker above a line to silence a specific finding. A non-empty reason is required:

| Language | Marker |
|---|---|
| PHP / JS / Vue `<script>` | `// ai-review:ignore Internal CLI, no HTTP exposure` |
| Blade | `{{-- ai-review:ignore Trusted internal value --}}` |
| Vue `<template>` / HTML | `<!-- ai-review:ignore Markdown rendered from CMS --> ` |

The skill skips findings within 2 lines below a marker.

### Dismissing a posted finding

If a posted comment is a false positive, mark it won't-fix:

```bash
.claude/skills/code-reviewer/bin/ai-review dismiss \
  --comment-id=1234 \
  --reason="Internal-only endpoint, auth handled by middleware"
```

The comment is updated with a ❌ banner and a hidden marker. The **next** `/code-reviewer` run reads dismissals from the PR and skips matching findings (same file, same dimension, line within ±5). To re-evaluate everything, pass `--ignore-dismissals`.

### Responding to developer replies

If a developer replies to one of the bot's review comments — to push back, ask a question, or say they've fixed it — the next `/code-reviewer` run reads the thread and responds:

- **Push-back it agrees with** → replies conceding, and dismisses the finding so it won't be re-flagged.
- **Push-back it disagrees with** → replies explaining why the finding still stands.
- **A question** → answers inline.
- **"I fixed it"** → verifies against the current code and, if genuinely addressed, replies and marks the finding resolved.

It shows you the drafted replies and asks before posting. Because a reply doesn't add a commit, the bot answers on the next run — including a re-run with no new commits to review. (Live, reply-time responses arrive with the hosted/CI version.)

### Review a branch without checking it out

Pass `--branch=<name>` or `--pr=<N>` to review a different branch (or PR) without touching your local checkout:

```
/code-reviewer --branch=feature/payments
/code-reviewer --pr=42
```

The skill fetches the branch, spins up a `git worktree` in a temp directory, runs the full review inside it, posts findings to the PR, then removes the worktree. Your current checkout is untouched throughout.

Use `--pr=<N>` when you only know the PR number. The skill resolves the branch name from Bitbucket automatically (requires credentials).

### Incremental review

Re-runs are incremental by default. Once a checkpoint exists, the skill automatically reviews only commits added since the last run — no flag needed.

To force a full re-review of the entire branch against `develop`:

```
/code-reviewer --full-review
```

The checkpoint is stored as a hidden PR comment — shared across machines, CI, and teammates.

### Telemetry

Each run prints a digest of how many findings were resolved, are still open, or have gone stale (>14 days). A snapshot is saved to `.ai-review/stats.json` so you can track signal-vs-noise per dimension over time.

### Want to fix locally instead?

If you're the developer cleaning up your own branch (rather than reviewing someone else's PR), use the `code-fixer` skill instead — see [below](#code-fixer-developer-skill).

### CI / headless mode (preview)

`code-reviewer` can run non-interactively for CI, driven by `skill/bin/ai-review-ci`. It invokes the skill via `claude --print --bare`, auto-confirming every prompt (set by `AI_REVIEW_CI=1`), and posts findings + syncs the Jira card with no human in the loop.

```bash
ANTHROPIC_API_KEY=sk-ant-...   # required for headless invocation
BITBUCKET_EMAIL=...            # required (skill posts via Bitbucket REST)
BITBUCKET_API_TOKEN=...
BITBUCKET_PR_ID=42             # auto-set by Bitbucket Pipelines on PR steps
.claude/skills/code-reviewer/bin/ai-review-ci
```

Optional knobs: `AI_REVIEW_MAX_USD` (spend cap, default 5.00), `AI_REVIEW_MODEL` (e.g. `sonnet`), `AI_REVIEW_OUTPUT` (JSON output path). Exit codes: `0` ran, `1` infra failure (missing env / no `claude` CLI), `2` the run errored.

> **Preview:** the wrapper works on any host with the `claude` CLI on `PATH` and is good for local dry-runs (`AI_REVIEW_CI=1`). A turnkey Bitbucket Pipe (Docker image + `bitbucket-pipelines.yml` template) is still in progress — until then you supply the `claude` CLI and pipeline yaml yourself.

## Updating

Each time you run `/code-reviewer` or `/code-fixer`, the skill checks its installed version against the latest on GitHub. If it's out of date, it asks before continuing:

```
⚠️  code-reviewer is out of date (installed: 1.0.0, latest: 1.1.0).
   Update before continuing:

     npx github:seangalabin/laravel-code-reviewer

Update now? [y/n]
```

- **y** — runs the update and stops; run `/code-reviewer` again to use the latest version
- **n** — stops; update manually and re-run

The check is skipped silently if GitHub is unreachable.

---

## code-fixer (developer skill)

Use `code-fixer` when you want to clean up your **own** branch before pushing — it runs the same 15-dimension analysis as `code-reviewer` but instead of posting comments to Bitbucket, it walks you through applying fixes interactively on your local machine. No credentials needed.

### When to use it

| Scenario | Use |
|---|---|
| Reviewing someone else's PR and posting feedback | `/code-reviewer` |
| Cleaning up your own branch before pushing | `/code-fixer` |

### Install

Run this once in your Laravel project root:

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer
```

To install into a specific directory:

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer /path/to/project
```

No credentials or `.env` changes needed — `code-fixer` never contacts Bitbucket.

### First run

Make sure you're on your feature branch (not `main`, `master`, or `develop`), then open Claude Code and run:

```
/code-fixer
```

The skill will:

1. Check its version is up to date
2. Diff your branch against `develop`
3. Scan for issues across all 15 review dimensions
4. Print a summary: `Found 5 issues (1 critical, 3 warnings, 1 suggestion). Starting fix loop.`
5. Check for uncommitted changes — if any exist, ask whether to proceed
6. Walk through each issue one at a time, Critical → Warning → Suggestion

### The fix loop

For each issue the skill prints:

1. **The problem** — plain English, what's wrong and why it matters
2. **AI fix prompt** — a copy-pasteable prompt you can hand to Claude Code to fix it
3. **Suggested fix** — a diff showing the exact change
4. **Why this fix** — what it prevents and how it connects to the codebase rules
5. **Suggested Pest test** — *only when the fix changes behaviour* (bug, security, new logic, data integrity, API contract). Pure-style fixes skip this.

Then it asks:

```
Apply this fix? [y/n/s/q]
```

| Key | Action |
|---|---|
| `y` | Apply the diff to the file immediately |
| `n` | Skip this issue |
| `s` | Skip all remaining issues at this severity level |
| `q` | Stop the loop and keep everything applied so far |

After each applied fix, the skill verifies it immediately by running **Pint**, **Pest** (both scoped to the changed files), and **lint** (`npm run lint`, if the fix touched JS/Vue/TS and a `lint` script exists). A failing check is surfaced right away so you can stop and inspect.

At the end it prints which files were modified, the verification status, and reminds you to run the full suite before pushing.

### Suppressing a finding

If a finding is a false positive, add an ignore marker on the line above the flagged code:

| Language | Marker |
|---|---|
| PHP / JS / Vue `<script>` | `// ai-review:ignore <reason>` |
| Blade | `{{-- ai-review:ignore <reason> --}}` |
| Vue `<template>` / HTML | `<!-- ai-review:ignore <reason> -->` |

A non-empty reason is required — bare markers without a reason are flagged as a suggestion.

### Applied fixes log

Every fix you accept is logged to `.ai-review/applied-{timestamp}.log` so you can review or revert what was changed.

---

## Development

### Editing the skills — source of truth

**`skill/SKILL.md` and `skill-fixer/SKILL.md` are generated. Never edit them by hand.** Edit the inputs and rebuild:

- The 15-dimension review lens (shared by both skills) lives in `src/review-lens.md`.
- Everything else lives in the per-skill templates: `skill/SKILL.template.md` and `skill-fixer/SKILL.template.md` (each pulls in the lens via `<!-- include:src/review-lens.md -->`).

After editing a template or the lens, regenerate:

```bash
python3 build.py
```

Commit the template(s), `src/review-lens.md`, and the regenerated `SKILL.md` files together.

> A hand-edit to a generated `SKILL.md` is silently destroyed by the next `python3 build.py`. The `TestBuildIdempotency` test guards against this — it fails if any committed `SKILL.md` differs from `expand(template)`. Run the tests before committing.

### Shared scripts

`scan_diff.py` is duplicated verbatim in both `skill/` and `skill-fixer/` and **must stay byte-identical** — edit one, copy it to the other. `TestSharedFilesNoDrift` fails if they diverge. (`check_version.sh` and `branch_summary.sh` are intentionally per-skill — don't sync those. Pint/Pest scripts live only in `code-fixer`.)

### Versioning

The two skills version **independently**. `skill/VERSION` and `skill-fixer/VERSION` are each compared against their own copy on GitHub by the running skill, which forces an update when they differ. Bump the VERSION of every skill a change actually ships to:

- A change to the **shared lens** (`src/review-lens.md`) affects both skills → bump **both** VERSION files.
- A change to **one skill only** (e.g. a reviewer-only flag, or fixer-only Windows support) → bump **only that skill's** VERSION.

Size the bump to the change (semver):

- **Patch** (`1.2.0` → `1.2.1`) — wording tweaks, small fixes, doc-only changes to a skill.
- **Minor** (`1.2.0` → `1.3.0`) — a new review rule, flag, or capability (backwards-compatible).
- **Major** (`1.2.0` → `2.0.0`) — breaking changes to how the skill is invoked or installed.

> `package.json`'s `version` tracks the **installer bundle** (this npm package), not the skills. It is independent of the two `VERSION` files, which are the authoritative source for the in-skill update check.

### Running tests

```bash
python3 -m unittest discover tests
```
