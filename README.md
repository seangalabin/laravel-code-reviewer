# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects. It serves two audiences:

- **Reviewers** — analyze a PR and post inline comments to Bitbucket
- **Developers** — analyze their own branch and apply suggested fixes locally before pushing

Same skill, chosen mode after the analysis runs.

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Refuse to run on `main`, `master`, or `develop` (feature branches only)
2. Diff the current branch against `develop`
3. Run a mechanical pre-pass (`scan_diff.py`) over the changed lines to surface red flags
4. Apply a 14-dimension review lens to every hunk
5. Count issues by severity and **ask you which mode to run**

### The three modes

**Mode 1 — Post as review**
Publish all findings as inline Bitbucket PR comments. Use this when you're reviewing someone else's code. Posts a disclaimer header first, then one comment per issue with a copy-pasteable fix prompt and an auto-apply command.

**Mode 2 — Fix locally**
Walk through each issue interactively and apply suggested fixes directly to the files in the branch. Use this when you're the developer cleaning up your own code before pushing. Never commits anything — just edits files.

**Mode 3 — Show me first**
Print the full review to the terminal so you can read it before deciding. Nothing is posted or changed.

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
| 🔴 | **Critical** | Bug, security issue, data loss risk. Creates a blocking task in Mode 1. |
| 🟡 | **Warning** | Likely problem, performance, maintainability. |
| 🔵 | **Suggestion** | Style, readability, minor improvement. |

Each finding contains: what's wrong in plain language, a copy-pasteable Claude Code prompt to fix it, a suggested diff, and an explanation of why the fix works.

## Requirements

- Node.js 16+
- Laravel project with [PestPHP](https://pestphp.com/) and [Laravel Pint](https://laravel.com/docs/pint)
- [Claude Code](https://claude.ai/code) CLI
- A Bitbucket repository (Mode 1 also requires an open PR)

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

The skill auto-detects the current branch, diffs it, runs the analysis, then asks which mode to use.

### Mode 1 — Reviewing someone else's code

```
/code-reviewer
> I found 5 issues (1 critical, 3 warnings, 1 suggestion).
> Reply with 1, 2, or 3.
1
> Posted 5 comments to PR #42. Review them at https://bitbucket.org/...
```

Each comment ends with an auto-apply command the developer can run:

```bash
.claude/skills/code-reviewer/bin/ai-review fix --comment-id=1234
```

### Mode 2 — Cleaning up your own branch

```
/code-reviewer
> I found 5 issues (1 critical, 3 warnings, 1 suggestion).
> Reply with 1, 2, or 3.
2
> Working tree is clean. Proceeding.
>
> 🔴 Critical — app/Http/Controllers/OrderController.php:34
> [full five-section issue...]
> Apply this fix? [y/n/s/q]
y
> ✓ Fixed app/Http/Controllers/OrderController.php:34
```

Applied fixes are logged to `.ai-review/applied-{timestamp}.log`. The skill never commits.

### Mode 3 — Read before deciding

```
/code-reviewer
> I found 5 issues (1 critical, 3 warnings, 1 suggestion).
> Reply with 1, 2, or 3.
3
> [prints full review to terminal]
> Would you like to go back and post (1) or fix locally (2)? [1/2/n]
```

### CLI flags

| Flag | Mode | Effect |
|---|---|---|
| `--force` | 2 | Bypass the 20-file-per-run cap |

## Updating

Re-run the install command in your project to get the latest version:

```bash
npx github:seangalabin/laravel-code-reviewer
```

---

## code-fixer (developer skill)

A companion skill for developers. Same review analysis, no Bitbucket posting — goes straight to an interactive fix loop on your local branch.

### Install

```bash
npx github:seangalabin/laravel-code-reviewer --skill=fixer
```

Or using the separate binary:

```bash
npx @redhq/code-reviewer code-fixer
```

### Usage

```
/code-fixer
```

The skill analyzes the branch, prints a summary, runs pre-flight checks (dirty tree, file cap), then walks through each issue asking `[y/n/s/q]`.
