# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects and posts inline comments directly to the PR.

For developers who want to fix issues on their own branch before pushing (instead of posting to a PR), use the companion skill [`code-fixer`](#code-fixer-developer-skill).

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Refuse to run on `main`, `master`, or `develop` (feature branches only)
2. Check previously posted comments and mark any that have been addressed
3. Refresh dismissal memory — skip findings a developer has already marked won't-fix
4. Diff the current branch against `develop`
5. Run a mechanical pre-pass (`scan_diff.py`) over the changed lines to surface red flags
6. Apply a 14-dimension review lens to every hunk
7. Ask: **Post {N} findings to PR #{ID}? [y/n]** — the only interactive prompt
8. Post each finding as an inline Bitbucket PR comment with a copy-pasteable fix prompt and an auto-apply command

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

Restart Claude Code to pick up the new environment variables.

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

Each comment ends with an auto-apply command the developer can run:

```bash
.claude/skills/code-reviewer/bin/ai-review fix --comment-id=1234
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

## Updating

Each time you run `/code-reviewer` or `/code-fixer`, the skill checks its installed version against the latest on GitHub. If it's out of date, it stops and tells you to update before continuing:

```
⚠️  code-reviewer is out of date (installed: 1.0.0, latest: 1.1.0).
   Update before continuing:

     npx github:seangalabin/laravel-code-reviewer
```

To update manually, re-run the install command in your project:

```bash
npx github:seangalabin/laravel-code-reviewer
```

The check is skipped silently if GitHub is unreachable.

---

## code-fixer (developer skill)

A companion skill for developers. Same review analysis, no Bitbucket posting — goes straight to an interactive fix loop on your local branch.

### Install

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer
```

To install into a specific directory:

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer /path/to/project
```

### Usage

```
/code-fixer
```

The skill analyzes the branch, prints a summary, runs pre-flight checks (dirty tree, file cap), then walks through each issue asking `[y/n/s/q]`.

---

## Development

### Editing the review lens

The 14-dimension review lens lives in `src/review-lens.md` and is shared between both skills. After editing it, regenerate both `SKILL.md` files:

```bash
python3 build.py
```

Commit `src/review-lens.md`, `skill/SKILL.md`, and `skill-fixer/SKILL.md` together.

### Running tests

```bash
python3 -m unittest discover tests
```
