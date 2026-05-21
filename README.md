# laravel-code-reviewer

A [Claude Code](https://claude.ai/code) skill that reviews pull requests on Laravel / Bitbucket projects and posts inline comments directly to the PR.

## What it does

Run `/code-reviewer` in Claude Code and it will:

1. Diff the current branch against `develop`
2. Run Pint, Pest, and ESLint as gates
3. Apply the rules from `.coderabbit.yaml` and `CLAUDE.md`
4. Post each finding as an **inline comment** on the Bitbucket PR, anchored to the exact file and line
5. Post a compliance summary (gate results + merge verdict) as a top-level PR comment

## Requirements

- Node.js 16+
- PHP project using [PestPHP](https://pestphp.com/), [Laravel Pint](https://laravel.com/docs/pint), and [ESLint](https://eslint.org/)
- [Claude Code](https://claude.ai/code) CLI
- A Bitbucket repository with an open PR for the branch being reviewed

## Installation

Run this inside any Laravel project:

```bash
npx github:seangalabin/laravel-code-reviewer
```

To install into a specific directory:

```bash
npx github:seangalabin/laravel-code-reviewer /path/to/project
```

This copies the skill files into `.claude/skills/code-reviewer/` in the target project.

## Setup

After installing, add your Bitbucket credentials to `.claude/settings.local.json` in the project root (this file is gitignored — each developer does this once):

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

Then restart Claude Code to pick up the new environment variables.

## Usage

Open Claude Code in your Laravel project and run:

```
/code-reviewer
```

That's it. The skill auto-detects the current branch, finds the open PR, runs all gates, and posts findings.

## How findings are posted

| Finding type | Posted as |
|---|---|
| MUST FIX / WARN with a file + line | Inline comment on that line in the PR |
| Compliance summary | Top-level PR comment |

**MUST FIX** — blocks merge (direct Eloquent in controller, missing types, N+1 queries, security issues, failing gates).

**WARN** — should be addressed but doesn't block (style drift, dead code, minor perf).

## Updating

When the skill is updated in this repo, re-run the install command in your project to get the latest version:

```bash
npx github:seangalabin/laravel-code-reviewer
```
