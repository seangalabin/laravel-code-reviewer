# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects and posts inline comments directly to the PR. It's an **opinionated reviewer that encodes one team's standards** — diff-scoped (only the lines your branch changed), severity-tagged, and run on your own Anthropic + Bitbucket credentials (code never goes to a third-party review service).

Two skills share the same 16-dimension review lens:

| Skill | For | What it does |
|---|---|---|
| **`code-reviewer`** | Reviewing someone's PR | Posts inline findings to the Bitbucket PR, syncs the Jira card |
| **`code-fixer`** | Cleaning up your own branch | Same analysis, no posting — walks you through applying fixes locally |

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Refuse to run on `main`, `master`, or `develop` (feature branches only)
2. Check previously posted comments — resolve any that have been addressed, and respond to developer replies
3. Skip findings a developer has already dismissed as won't-fix
4. Diff the current branch against `develop`
5. Run the review — a mechanical red-flag pre-scan, parallel lens-slice subagents on larger diffs, then main-context arbitration with a printed per-dimension coverage ledger
6. Ask: **Post {N} findings to PR #{ID}? [y/n]** — the only interactive prompt
7. Post each finding as an inline Bitbucket PR comment with a copy-pasteable fix prompt

It also reads the linked Jira card (title, acceptance criteria, comment thread) to judge whether the change solves the *right* problem, flag files unrelated to the task, and honour decisions made in the discussion.

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
| 11 | Migrations | Non-null without default (table lock risk), Model refs, empty `down()`, data-only migrations → seeders |
| 12 | Front-end framework | Auto-detects Vue / React / other JS-TS frameworks; list keys, state mutation, HTML-injection XSS, effect/listener leaks |
| 13 | Testing | Stray HTTP, reflection, `withoutExceptionHandling()`, missing assertions |
| 14 | API Design | Status codes, pagination, Resource field exposure |
| 15 | Blade views | Business logic in views, N+1 in `@foreach`, URL/attr XSS, CSRF, dynamic `@include` |
| 16 | Scalability & Large Data | `chunkById` over `chunk`, chunk-and-queue orchestration, job idempotency, retry safety, worker concurrency, Redis caching for hot reads, S3 over local disk |

Teams can extend or override the lens (disable a check, change a severity, add a project rule) in their project `CLAUDE.md`.

## Severity

| | Severity | When |
|---|---|---|
| 🔴 | **Critical** | Bug, security issue, data loss risk. Creates a blocking task on the PR. |
| 🟡 | **Warning** | Likely problem, performance, maintainability. |
| 🔵 | **Suggestion** | Style, readability, minor improvement. |

## Requirements

- Node.js 16+
- Laravel project with [PestPHP](https://pestphp.com/) and [Laravel Pint](https://laravel.com/docs/pint)
- [Claude Code](https://claude.ai/code) CLI
- **Model: Sonnet or Opus.** Both skills refuse to run on anything else (Fable, Haiku) — run `/model sonnet` before invoking. The fan-out slice agents are always Sonnet regardless of the session model.
- A Bitbucket repository with an open PR on the current branch
- **Shell:** Linux, macOS, or WSL/Git Bash (`.sh` scripts). Native **Windows** is supported via PowerShell variants and additionally needs **Python 3** and **curl** on `PATH`; the skill auto-detects the OS.

## Installation

```bash
npx github:seangalabin/laravel-code-reviewer                # current directory
npx github:seangalabin/laravel-code-reviewer /path/to/project
```

The installer copies the skill into `.claude/skills/code-reviewer/`, adds `allowedTools` entries to `.claude/settings.json` so the review scripts run without permission prompts, and scaffolds a starter **`CLAUDE.md`** of company engineering standards that the skills read as project overrides. An existing `CLAUDE.md` is never overwritten — you get a `CLAUDE.example.md` to merge instead.

## Setup

Add your Bitbucket credentials to `.claude/settings.local.json` in the project root (gitignored — each developer does this once), then restart Claude Code:

```json
{
  "env": {
    "BITBUCKET_EMAIL": "your@email.com",
    "BITBUCKET_API_TOKEN": "your_api_token"
  }
}
```

Create the API token with **Pull requests: write** scope at https://bitbucket.org/account/settings/personal-access-tokens/

**Optional — Jira card status sync.** To transition the linked card after each review (`Failed Code Review` when findings remain, `Code Review` when clean), also set `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` the same way. The email/token fall back to the Bitbucket values if the accounts share an Atlassian login; override the status names with `JIRA_FAILED_STATUS` / `JIRA_PASSED_STATUS` if your workflow labels differ. If any Jira variable is missing, the sync soft-skips — the review itself never fails.

## Usage

```
/code-reviewer
> Found 5 issues (1 critical, 3 warnings, 1 suggestion) on branch feature/payments.
> Post to PR #42? [y/n]
y
> Posted 5 comments to PR #42. Review them at https://bitbucket.org/...
```

### Flags

| Flag | What it does |
|---|---|
| `--branch=<name>` / `--pr=<N>` | Review another branch (or PR) in a temporary `git worktree` — your checkout is untouched. `--pr` resolves the branch from Bitbucket. |
| `--full-review` | Re-review the whole branch. Re-runs are otherwise **incremental** — only commits since the last run's checkpoint (stored as a hidden PR comment, shared across machines and CI). |
| `--ignore-dismissals` | Re-evaluate findings previously dismissed as won't-fix. |

### Suppressing a finding in code

Add a marker above the line (the skill skips findings within 2 lines below it). A non-empty reason is required — bare markers are themselves flagged:

| Language | Marker |
|---|---|
| PHP / JS / Vue `<script>` | `// ai-review:ignore Internal CLI, no HTTP exposure` |
| Blade | `{{-- ai-review:ignore Trusted internal value --}}` |
| Vue `<template>` / HTML | `<!-- ai-review:ignore Markdown rendered from CMS -->` |

### Dismissing a posted finding

```bash
.claude/skills/code-reviewer/bin/ai-review dismiss \
  --comment-id=1234 \
  --reason="Internal-only endpoint, auth handled by middleware"
```

The comment gets a ❌ banner and its inline thread is resolved (collapses in the Bitbucket UI). Subsequent runs skip matching findings (same file and dimension, line within ±5) — and won't re-post a finding already on the PR, open or resolved, so `--full-review` or a later edit near a fixed line won't resurrect it.

### Developer replies

If a developer replies to a bot comment, the next run reads the thread and responds: it concedes and dismisses when the push-back is right, explains why the finding stands when it isn't, answers questions, and verifies "I fixed it" claims against the current code before resolving. Drafted replies are shown for approval before posting.

### Giving the reviewer your implementation context

The reviewer sees the diff, not the reasoning behind it — the main cause of "you flagged something I did on purpose". Paste a short rationale where it already looks: the **PR description** or a **Bitbucket/Jira comment** (inline text, not a file attachment):

```markdown
<!-- ai-review:context -->
## Implementation notes
- Skipped the cache layer here — this path runs once per import, not per request.
- Chose a raw upsert over the Repository: 200k rows, the ORM path timed out.
```

A deliberate, explained trade-off won't be flagged as a mistake — but the block never overrides correctness or security: a real 🔴 stands, and a flawed rationale gets challenged.

### Telemetry

Each run prints a resolved / open / stale digest and snapshots per-dimension stats to `.ai-review/stats.json`, so you can track signal-vs-noise over time.

### CI / headless mode (preview)

`skill/bin/ai-review-ci` runs the skill non-interactively (`claude --print --bare`, auto-confirming prompts) — posts findings and syncs the Jira card with no human in the loop:

```bash
ANTHROPIC_API_KEY=sk-ant-...   # required for headless invocation
BITBUCKET_EMAIL=...            # required (skill posts via Bitbucket REST)
BITBUCKET_API_TOKEN=...
BITBUCKET_PR_ID=42             # auto-set by Bitbucket Pipelines on PR steps
.claude/skills/code-reviewer/bin/ai-review-ci
```

Optional knobs: `AI_REVIEW_MAX_USD` (spend cap, default 2.00 — a runaway ceiling, you pay actual usage; don't set below ~1.00 or a mid-run kill bills tokens but posts nothing), `AI_REVIEW_MODEL` (`sonnet` default or `opus`; anything else fails pre-flight — the skill runs on those two only), `AI_REVIEW_OUTPUT` (JSON output path). Exit codes: `0` ran, `1` infra failure (missing env / no `claude` CLI / unsupported model), `2` the run errored. Works on any host with the `claude` CLI on `PATH`.

**Run it automatically on every PR.** A Bitbucket Pipelines `pull-requests:` trigger runs the review when a PR is opened and on each push to its source branch — exactly the cadence the incremental checkpoint was built for. Copy [`assets/bitbucket-pipelines.example.yml`](assets/bitbucket-pipelines.example.yml) to your repo root (or, if you already have a pipeline, merge in its `ai_review` anchor — the file shows how). Then enable Pipelines and add three secured repository variables: `ANTHROPIC_API_KEY`, `BITBUCKET_EMAIL`, and `BITBUCKET_API_TOKEN` (Pull requests: write). `BITBUCKET_PR_ID` / `BITBUCKET_BRANCH` are provided by Bitbucket automatically. Two load-bearing details the example handles: `clone: depth: full` (a shallow clone hides the base-branch diff ref) and posting as a dedicated **bot** account (comments appear as whoever owns the API token). The diff base defaults to `develop`; for a repo that integrates into `master` (or any other branch) set `AI_REVIEW_BASE_BRANCH` as a repo variable — the example's fetch and the skill both honour it.

## Updating

Each run checks its installed version against GitHub and offers to update before continuing (skipped silently if GitHub is unreachable).

---

## code-fixer (developer skill)

The same 16-dimension analysis for your **own** branch before pushing — no posting, no credentials, fixes applied interactively on your machine.

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer                  # current directory
npx github:seangalabin/laravel-code-reviewer --skill=fixer /path/to/project
```

On your feature branch, run `/code-fixer`. It diffs against `develop`, scans all 16 dimensions, warns about uncommitted changes, then walks each issue Critical → Warning → Suggestion. For every issue it prints the problem, a copy-pasteable AI fix prompt, the suggested diff, why it matters, and — only when the fix changes behaviour — a suggested Pest test. Then:

```
Apply this fix? [y/n/s/q]
```

| Key | Action |
|---|---|
| `y` | Apply the diff to the file immediately |
| `n` | Skip this issue |
| `s` | Skip all remaining issues at this severity level |
| `q` | Stop the loop and keep everything applied so far |

Each applied fix is verified immediately — **Pint**, **Pest** (scoped to the changed files), and `npm run lint` when JS/Vue/TS was touched — and logged to `.ai-review/applied-{timestamp}.log`. Suppression markers work the same as [in code-reviewer](#suppressing-a-finding-in-code).

---

## Development

### Editing the skills — source of truth

**`skill/SKILL.md` and `skill-fixer/SKILL.md` are generated. Never edit them by hand.** Edit the inputs and rebuild:

- The 16-dimension review lens (shared by both skills) lives in `src/review-lens.md`.
- Everything else lives in the per-skill templates: `skill/SKILL.template.md` and `skill-fixer/SKILL.template.md` (each pulls in the lens via `<!-- include:src/review-lens.md -->`).

After editing a template or the lens, regenerate and commit the inputs together with the regenerated `SKILL.md` files:

```bash
python3 build.py
```

> A hand-edit to a generated `SKILL.md` is silently destroyed by the next `python3 build.py`. The `TestBuildIdempotency` test fails if any committed `SKILL.md` differs from `expand(template)`.

### Shared scripts

`scan_diff.py` is duplicated verbatim in both `skill/` and `skill-fixer/` and **must stay byte-identical** — edit one, copy it to the other (`TestSharedFilesNoDrift` fails if they diverge). `check_version.sh` and `branch_summary.sh` are intentionally per-skill; Pint/Pest scripts live only in `code-fixer`.

### Versioning

The two skills version **independently** via `skill/VERSION` and `skill-fixer/VERSION` (each drives that skill's self-update check). Bump every skill a change actually ships to: a shared-lens change bumps **both**; a single-skill change bumps only that one. Size the bump with semver — patch for wording/small fixes, minor for a new rule/flag/capability, major for breaking invocation or install changes.

> `package.json`'s `version` tracks the **installer bundle** (this npm package), not the skills — the two `VERSION` files are authoritative for the in-skill update check.

### Running tests

```bash
python3 -m unittest discover tests
```
