---
name: code-reviewer
description: Diff-scoped code review for the current branch. Reviews ONLY the lines changed since the base branch (develop) — not entire files. Covers architecture & layering, PSR-12, security, Laravel best practices, testability, and Vue/JS quality.
---

# Code Reviewer

Reviews the **current branch's changes** against the base branch (`develop` for this repo). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## OS detection (once, before Step -1)

`code-reviewer` runs its scripts through **bash** (Linux, macOS, WSL, or Git Bash on Windows). It has no native PowerShell variant. Confirm a bash shell is available before doing anything else:

**Step A.** Run `uname -s`.
- Returns `Linux` → bash is available (Linux / WSL). Continue.
- Returns `Darwin` → bash is available (macOS). Continue.
- Returns a value starting with `MINGW` or `CYGWIN` → bash is available (Git Bash on Windows). Continue.
- Errors or returns anything else → go to Step B.

**Step B.** No bash shell (native Windows PowerShell/cmd). **Stop immediately** and print:

> ❌ `code-reviewer` needs a bash shell. On Windows, install **Git Bash** or **WSL** and re-run from there — or use `/code-fixer`, which has native Windows support.

Do not attempt to run the `.sh` scripts without bash — they will fail.

---

## Step -1 — Version check (always first, before anything else)

```bash
.claude/skills/code-reviewer/scripts/check_version.sh
```

- Exit **0** → continue normally.
- Exit **1** → print the script's output, then ask:

  > Update now? [y/n]

  **y** → run the update:
  ```bash
  npx github:seangalabin/laravel-code-reviewer
  ```
  Then stop. Print: `Updated. Run /code-reviewer again to use the latest version.`

  **n** → stop. Print: `Skipped. Run /code-reviewer again after updating.`

---

## Global constraints

These apply in all modes and cannot be overridden by project config:

- **Never auto-commit.** Apply or post findings only — never run `git commit`, `git push`, or any destructive git operation.
- **Refuse on protected branches.** If the current branch is `main`, `master`, or `develop`, stop immediately: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`

---

## Step 0 — Set up review target (only when `--branch` or `--pr` is passed)

**If neither flag was passed, skip to Step 0.1.** The review targets the currently checked-out branch.

**If `--branch=<name>` or `--pr=<N>` was supplied:**

1. Guard — refuse if the target is a protected branch (`main`, `master`, `develop`). `setup_target.sh` enforces this too, but catch it here first:

   > `ERROR: Refusing to review protected branch '<name>'. Check out your feature branch first.`

2. Store the skills root (absolute path so it survives a `cd`):
   ```bash
   SKILLS_ROOT=$PWD/.claude/skills/code-reviewer
   ```

3. Run the setup script and capture the worktree path:
   ```bash
   WORKTREE=$(bash "$SKILLS_ROOT/scripts/setup_target.sh" [--branch=<name>|--pr=<N>])
   ```
   The script fetches the branch, creates a detached `git worktree` at a temp path (e.g. `/tmp/ai-review-abc123`), writes `.ai-review/target.json` inside it, and prints the path.

4. **For the remainder of this run, apply these three rules to every command:**

   | Command type | Normal mode | Target mode |
   |---|---|---|
   | Run a script | `.claude/skills/code-reviewer/scripts/foo.sh` | `cd "$WORKTREE" && "$SKILLS_ROOT/scripts/foo.sh"` |
   | Run a git command | `git diff ...` | `git -C "$WORKTREE" diff ...` |
   | Read a file | `Read app/Foo.php` | `Read $WORKTREE/app/Foo.php` |

   All `.ai-review/` state (dismissals, stats, target.json) lives inside `$WORKTREE`. All Bitbucket scripts auto-detect `target.json` and use its `branch` / `pr_id` instead of the current git state — no extra arguments needed.

5. **At the very end** of this run (after cleanup/checkpoint/telemetry), remove the worktree:
   ```bash
   bash "$SKILLS_ROOT/scripts/cleanup_target.sh" "$WORKTREE"
   ```

6. **On any error after this point** — if the run aborts before reaching step 5, still clean up:
   ```bash
   bash "$SKILLS_ROOT/scripts/cleanup_target.sh" "$WORKTREE"
   ```
   A leaked worktree leaves a stale `git worktree` entry. Run `git worktree prune` in the main repo to remove orphaned entries if this happens.

---

## Step 0.1 — Check for project-specific overrides (optional)

**Company review rules.** If `.claude/code-review-rules.md` exists, read it and apply its rules **in addition to** the built-in lens below. These are first-class:

- A company rule takes **precedence** over a built-in rule when they conflict.
- A company rule may **disable** a built-in dimension (e.g. "Disable dimension 6") — honour that and skip the built-in check.
- Apply company rules with the same weight as the lens — flag violations at the severity the rule states.

If the project also has any of these files in the root, read them first and let them override the defaults in this skill:

- `CLAUDE.md` — project conventions for Claude Code
- `.coderabbit.yaml` — CodeRabbit review rules (if present)
- `.cursorrules` or `.github/copilot-instructions.md` — other agent rules

If none exist, skip this step. The skill's built-in rules are reasonable Laravel defaults and work standalone.

---

## Scope rule (read this before touching files)

**Review only what the branch changed.** That means:

- Added or modified lines in the diff — fair game, always.
- Deleted lines — fair game if the deletion introduces a regression or removes a guard.
- Pre-existing lines **inside a touched hunk** — fair game when the surrounding change makes them newly relevant.
- Pre-existing lines **outside any hunk, in a file the branch did not touch** — out of scope. Do not surface.
- Files the branch did not touch — out of scope. Do not open them looking for issues.

When a pre-existing issue is in a touched hunk, label it `(pre-existing, but touched)`.

**Do not flag issues already caught by Pint (formatting/style) or the Pest ArchitectureTest (suffix rules, base-class rules, enum rules).** Those run in CI before the card reaches code review.

### Honor inline suppression markers

Developers can suppress a finding by placing a marker on the 1–2 lines immediately above the offending line. A non-empty reason is required.

| Language | Marker |
|---|---|
| PHP / JS / Vue `<script>` | `// ai-review:ignore <reason>` |
| Blade | `{{-- ai-review:ignore <reason> --}}` |
| Vue `<template>` / HTML | `<!-- ai-review:ignore <reason> -->` |

When you encounter one of these markers above a line you would otherwise flag, **skip the finding**. The scan_diff.py pre-pass already honors these — apply the same rule to anything you would flag yourself. Empty reasons do not count as a valid suppression — flag those as a 🔵 Suggestion ("ignore marker missing reason").

---

## Scoping the review

### Refresh from the remote first

In normal mode, the review compares against `origin/develop` and the current branch on Bitbucket. Stale remote-tracking refs — or a local HEAD that lags the remote — will hide new commits from the checkpoint comparison and produce a false "no new commits" result. Refresh before resolving the diff base:

```bash
.claude/skills/code-reviewer/scripts/refresh_branch.sh
```

The script fetches `origin/develop` and `origin/<branch>`, then aligns the local branch:

- Behind only → fast-forwards local to match the remote.
- Diverged or has unpushed commits → leaves HEAD alone and warns; the review proceeds against the local view.
- Fetch fails (offline, no remote) → warns and continues.

**Skip this step in target mode (`--branch`/`--pr`)** — `setup_target.sh` already fetched the branch and the worktree is detached at the fresh `origin/<branch>`. The script no-ops if it detects target mode.

### Determine the diff base

**Unless `--full-review` was passed**, always try the checkpoint first:

```bash
CHECKPOINT_SHA=$(.claude/skills/code-reviewer/scripts/get_checkpoint.sh)
HEAD_SHA=$(git rev-parse HEAD)
```

The script reads a hidden checkpoint comment on the PR and prints the SHA — or nothing if no checkpoint exists yet.

- `CHECKPOINT_SHA` **non-empty AND equals `HEAD_SHA`** → the PR has already been reviewed at the current tip. Print exactly this, then **stop the run** (do not run scoping, analysis, or posting):

  > `PR #{ID} was last reviewed at {short_sha}, which is still the current tip. 0 new commits to review since the last run. Pass --full-review to re-review the whole branch against develop.`

- `CHECKPOINT_SHA` **non-empty AND differs from `HEAD_SHA`** → `BASE_REF=$CHECKPOINT_SHA`. Print: `Reviewing commits since {short_sha} (last review checkpoint). Pass --full-review to review the full branch.`
- `CHECKPOINT_SHA` **empty** → `BASE_REF=origin/develop`. Print: `No checkpoint found — running full review against develop.`

**If `--full-review` was passed:** skip `get_checkpoint.sh` and set `BASE_REF=origin/develop` directly. Print: `Full review against develop.`

> `--since-last-review` is accepted as an alias for the default behaviour (no-op).

### Run the scoping scripts

```bash
.claude/skills/code-reviewer/scripts/branch_summary.sh "$BASE_REF"
.claude/skills/code-reviewer/scripts/scan_diff.py --base "$BASE_REF"
```

Then read the full diff:

```bash
git diff ${BASE_REF}...HEAD    # source of truth for scope
```

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter.

---

## Step 0.5 — Check previously posted comments

Run this before the new diff analysis:

```bash
.claude/skills/code-reviewer/scripts/check_resolved.py
```

This outputs a JSON array of open AI review comments on the current PR — comments that were posted by a previous run of this skill and haven't been marked resolved yet. If the array is empty, skip to the Workflow.

For each comment in the array:

1. Read the current code at `{path}:{line}` in the working tree.
2. Read the `problem` field (the plain-English issue from section 1 of the original comment).
3. **Evaluate: does the current code at that location actually address the stated problem?** Apply judgement — a trivial edit, a rename, or an unrelated change is **not** a fix.
4. If **resolved**: find the oldest commit after `posted_sha` that touched the file:
   ```bash
   git log --oneline {posted_sha}..HEAD -- {path}
   ```
   Take the **last line** of that output (earliest commit). Then update the comment:
   ```bash
   .claude/skills/code-reviewer/scripts/update_resolved.py --comment-id={id} --fix-sha={fix_sha}
   ```
5. If **not resolved**: leave the comment as-is.

Print a summary before continuing:
> Checked {N} previous comment(s): {X} resolved ✅, {Y} still open.

---

## Step 0.6 — Refresh dismissal memory

Pull any dismissed findings from the PR so we don't re-flag what a human has already said is acceptable:

```bash
.claude/skills/code-reviewer/scripts/check_dismissals.py
```

This writes `.ai-review/dismissals.json`. Each entry records `path`, `line`, `dim`, `severity`, `sig`, and a `reason` the developer provided when running `ai-review dismiss`.

If `--ignore-dismissals` was passed when invoking the skill, **still run the refresh** but ignore the file's contents in Step 1. The flag is a one-time re-evaluation, not a memory wipe.

---

## Workflow

### Step 1 — Analyze

1. **Load project rules** (Step 0.1 above).
2. **Refuse if on a protected branch.** In normal mode, run `git branch --show-current` (or `git -C "$WORKTREE" branch --show-current` in target mode — it returns empty for detached HEAD, which is safe). If the resolved branch is `main`, `master`, or `develop`, stop: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`
3. **Diff first.** Run the scoping scripts and read every hunk. Do not start by reading whole files.
4. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — findings on those files are out of scope unless changed.
5. **Apply the full review lens** (all sections below) to everything in the diff.
6. **Filter dismissals.** For every candidate finding, read `.ai-review/dismissals.json` and skip the finding if any entry matches:
   - same `path`, AND
   - same `dim` (from the dismissal `dim` field), AND
   - candidate line is within ±5 of the dismissal `line`

   Skip this filter entirely if `--ignore-dismissals` was passed.
7. **Compile remaining findings** grouped by severity (🔴 Critical → 🟡 Warning → 🔵 Suggestion). Do not post or modify any files yet.

### Step 2 — Post the review

1. Print a summary and ask for confirmation (**this is the only interactive prompt in the run**):

   > Found **{N} issues** ({X} critical, {Y} warnings, {Z} suggestions) on branch `{branch}`.
   > Post to PR #{ID}? [y/n]

2. **y** → post all findings as inline Bitbucket PR comments (see **Posting the review** below).
3. **n** → end here. Print: `Skipped. Run /code-reviewer again to post, or use /code-fixer to fix locally.`

Do not run any Bitbucket posting scripts until the user confirms **y**.

---

<!-- include:src/review-lens.md -->
## Output format

### Global rules

- **Plain language only.** Explain issues like you're talking to a junior dev on their first week. No jargon unless you immediately define it. Prefer "this runs the database query inside a loop, which is slow" over "N+1 query antipattern detected."
- **One issue per comment.** Do not bundle multiple problems into a single comment.
- **Be concrete.** Reference the actual variable, method, or line — not abstract concepts.

### AI disclaimer header

**Do not post the disclaimer yourself.** `post_review.sh` owns the AI disclaimer header — it posts the disclaimer once per PR, dedupes against any existing one (by hidden marker or signature), and skips re-posting on subsequent runs. Build the findings file and let the script handle the disclaimer.

This applies to every channel: do **not** include the disclaimer in inline finding bodies, do **not** post it as a separate top-level comment via `curl` or the Bitbucket API, do **not** paraphrase it. `post_review.sh` is the only place the disclaimer text exists, and the only place that writes it.

### Per-issue comment structure

Each inline comment must contain these five sections, in this exact order, with these exact headings:

#### 1. The problem (plain English)
One or two sentences. What's wrong, in the simplest words possible. No "consider refactoring" — say what's actually broken or risky and why it matters.

#### 2. AI fix prompt
A complete, copy-pasteable prompt the developer can hand to Claude Code (or any AI assistant) to fix this. It MUST include:
- File path (e.g. `app/Services/OrderService.php`)
- Line number or method name
- The exact problem in one sentence
- Relevant surrounding context (what the method does, what calls it, what the constraint is)
- Acceptance criteria for the fix

Wrap it in a fenced code block labeled ` ```prompt ` so it's easy to copy.

Example:
```prompt
In `app/Services/OrderService.php`, method `calculateTotals()` (around line 47):
The method queries the database inside a foreach loop, causing one query per order item.
This service is called on every checkout, so it scales badly under load.
Refactor it to load all related items in a single query before the loop.
Keep the existing return type and method signature. Do not change the public API.
Follow HQ's Controller → DTO → Service → Repository layering — the query belongs in the repository, not the service.
```

#### 3. Suggested fix (code)
Show the actual code change. Use a diff-style block when possible:

```diff
- foreach ($orders as $order) {
-     $items = OrderItem::where('order_id', $order->id)->get();
- }
+ $items = $this->orderItemRepository->findByOrderIds($orders->pluck('id'));
```

If a diff doesn't fit (e.g. new file), show the full replacement code block with the language tag.

#### 4. Why this fix
Two or three sentences. Explain *why* this fix works, not just *what* it does. Connect it to a concrete consequence (performance, security, readability, layering rule).

#### 5. Auto-fix command
At the end of every comment, include this exact line so the developer can apply the fix later:

```bash
.claude/skills/code-reviewer/bin/ai-review fix --comment-id={COMMENT_ID}
```

`{COMMENT_ID}` will be substituted with the actual Bitbucket comment ID by `post_review.sh` after posting.

### Severity tagging

Prefix each comment's title with one of:
- 🔴 **Critical** — bug, security issue, data loss risk. Creates a blocking task.
- 🟡 **Warning** — likely problem, performance, maintainability. Non-blocking.
- 🔵 **Suggestion** — style, readability, minor improvement. Optional.

---

### Posting the review

1. Post the required AI disclaimer header as the first top-level PR comment (see Required header above).
2. Compile all findings into a JSON array. Each entry needs:
   - `path`, `line` — where the issue lives
   - `body` — the full five-section comment including the auto-fix command with `{COMMENT_ID}` as a placeholder
   - `dim` — the dimension code from the Review lens (e.g. `"3a"`, `"4b"`, `"12"`). Used for telemetry.
   - `severity` — `"critical"`, `"warning"`, or `"suggestion"` (lowercase). Used for telemetry.
3. Post via `post_review.sh` (which resolves `{COMMENT_ID}` and embeds the telemetry marker after posting):

```bash
.claude/skills/code-reviewer/scripts/post_review.sh <<'FINDINGS'
[
  {
    "path": "app/Http/Controllers/UserController.php",
    "line": 22,
    "body": "🔴 **Critical** — ...\n\n### 1. The problem\n...",
    "dim": "3b",
    "severity": "critical"
  }
]
FINDINGS
```

4. Create a blocking task for every 🔴 Critical finding.
5. Save the review checkpoint:
   ```bash
   .claude/skills/code-reviewer/scripts/save_reviewed_sha.sh
   ```
6. Print the telemetry digest (resolved/open/stale across PR history):
   ```bash
   .claude/skills/code-reviewer/scripts/aggregate_stats.py
   ```
7. End with: `Posted {N} comments to PR #{ID}. Review them at {URL}.`
8. **Target mode only** — remove the worktree:
   ```bash
   bash "$SKILLS_ROOT/scripts/cleanup_target.sh" "$WORKTREE"
   ```
   Print: `Worktree cleaned up.`

If developers want to fix issues locally instead, they should use the `/code-fixer` skill (separate from `/code-reviewer`).

---

## What not to do

- Don't comment on style issues already caught by the linter (Pint, ESLint).
- Don't open untouched files to look for new issues.
- Don't grade the whole architecture from a small change.
- Don't restate `.coderabbit.yaml` rules verbatim if the project uses CodeRabbit — it already does that on the PR.
- Don't flag issues caught by Pint or the Pest ArchitectureTest.
- Don't invent issues to fill buckets. An empty 🔴/🟡 list is a valid and welcome outcome.
- Don't run Pint, Pest, or ESLint — CI runs these before the card moves to code review.
- Don't suggest rewrites of working code unless there's a concrete reason.
- Don't say "consider" or "you might want to" — be direct: "this will fail when X" or "this is fine, but Y is faster."
- Don't repeat the same issue across multiple lines. Comment once on the first occurrence and mention "same pattern appears at lines X, Y, Z."
- Don't reference the original codebase author or assign blame.

---

## Scripts

- **`branch_summary.sh [base]`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py [--base REF] [--no-snippets]`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`post_review.sh`** — posts the compiled review as inline Bitbucket PR comments. Reads JSON from stdin. Requires `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` env vars.
- **`setup_target.sh --branch=<name>|--pr=<N>`** — fetches a branch and creates a detached git worktree for reviewing without checkout. Writes `.ai-review/target.json` inside the worktree. Prints the worktree path to stdout.
- **`cleanup_target.sh <worktree-path>`** — removes a worktree created by `setup_target.sh`.

---

## Reference material

- `references/laravel_review_guide.md` — Laravel-specific patterns, anti-patterns, correctness traps
- `references/vue_review_guide.md` — Vue 3 / Vuex 4 patterns and component quality checks
- `references/coding_standards.md` — PSR-12, naming conventions, method length limits
- `references/common_antipatterns.md` — copy-paste reference for the most common violations
- `references/code_review_checklist.md` — quick checklist for every diff
