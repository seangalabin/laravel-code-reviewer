# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects and posts inline comments directly to the PR.

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Diff the current branch against `develop`
2. Run a mechanical pre-pass (`scan_diff.py`) over the changed lines to surface red flags
3. Apply a 14-dimension review lens to every hunk (see below)
4. Post each finding as an **inline comment** on the Bitbucket PR, anchored to the exact file and line
5. Post a scorecard (Architecture, PSR-12, Security, Testability) and merge verdict as a summary comment

If the project has a `.coderabbit.yaml` or `CLAUDE.md`, those rules are read first and take precedence over the skill's defaults. Neither file is required — the skill works standalone with sensible Laravel defaults.

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

| | Severity | Merge policy |
|---|---|---|
| 🔴 | **Critical** | Blocks merge immediately |
| 🟠 | **Major** | Must fix before merge |
| 🟡 | **Minor** | Should fix, doesn't block |
| 🔵 | **Suggestion** | Consider |

Each finding includes the offending code, an explanation of why it's a problem, and a corrected example.

## Requirements

- Node.js 16+
- Laravel project with [PestPHP](https://pestphp.com/) and [Laravel Pint](https://laravel.com/docs/pint)
- [Claude Code](https://claude.ai/code) CLI
- A Bitbucket repository with an open PR for the branch being reviewed

## Installation

**Option A — npx (recommended):**

```bash
npx github:seangalabin/laravel-code-reviewer
```

To install into a specific directory:

```bash
npx github:seangalabin/laravel-code-reviewer /path/to/project
```

**Option B — `.skill` file:**

Download `code-reviewer.skill` from this repo and install it via the Claude Code skill manager.

Both options copy the skill files into `.claude/skills/code-reviewer/` in the target project.

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

The skill auto-detects the current branch, finds the open PR, and posts findings.

## Updating

Re-run the install command in your project to get the latest version:

```bash
npx github:seangalabin/laravel-code-reviewer
```
