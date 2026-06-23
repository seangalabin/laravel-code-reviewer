---
name: code-reviewer
description: Diff-scoped code review for the current branch. Reviews ONLY the lines changed since the base branch (develop) — not entire files. Covers architecture & layering, PSR-12, security, Laravel best practices, testability, and Vue/JS quality.
---

# Code Reviewer

Reviews the **current branch's changes** against the base branch (`develop` for this repo). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## OS detection (once, before Step -1)

Detect the platform once — the result selects which script variant every later step uses. Stop as soon as a step resolves.

**Step A.** Run `uname -s`.
- `Linux` → **Unix mode** (`.sh` scripts). [Linux / WSL]
- `Darwin` → **Unix mode** (`.sh` scripts). [macOS]
- Starts with `MINGW` or `CYGWIN` → **Unix mode** (`.sh` scripts). [Git Bash on Windows — bash is available]
- Errors or anything else → go to Step B.

**Step B.** Run `python3 -c "import platform; print(platform.system())"` (or `python` if `python3` is unavailable).
- `Linux` or `Darwin` → **Unix mode** (`.sh` scripts).
- `Windows` → **Windows mode** (`.ps1` scripts).
- Errors → go to Step C.

**Step C.** Assume **Windows mode** and print:
> ⚠️ OS could not be detected — assuming Windows and using `.ps1` scripts.

**PowerShell launcher (Windows mode):** use `pwsh` (PowerShell 7+) if available; otherwise fall back to `powershell` (Windows PowerShell 5.1).

### Command translation (Windows mode only)

Every command in this document is written in **Unix mode**. In Windows mode, translate each line as you run it:

| Unix mode | Windows mode |
|---|---|
| `.claude/skills/code-reviewer/scripts/foo.sh [args]` | `pwsh .claude/skills/code-reviewer/scripts/foo.ps1 [args]` |
| `.claude/skills/code-reviewer/scripts/foo.py [args]` | `python .claude/skills/code-reviewer/scripts/foo.py [args]` |
| `bash "$SKILLS_ROOT/scripts/foo.sh" [args]` (target mode) | `pwsh "$SKILLS_ROOT/scripts/foo.ps1" [args]` |
| `VAR=$(cmd)` … then `$VAR` | `$VAR = (cmd)` … then `$VAR` |
| `git diff ${BASE_REF}...HEAD` | `git diff "$BASE_REF...HEAD"` |
| `cd "$WORKTREE" && cmd` (target mode) | `Set-Location $WORKTREE; cmd` |

The `.py` scripts (`scan_diff.py`, `check_resolved.py`, `check_dismissals.py`, `check_replies.py`, `update_resolved.py`, `post_reply.py`, `aggregate_stats.py`) are byte-identical across platforms — only the launcher differs (`python`). Each `.ps1` accepts the same arguments and reads the same `.ai-review/target.json` as its `.sh` counterpart — including `post_review`, which takes an optional findings-file path as its first argument (`post_review.ps1 .ai-review/findings.json`), falling back to stdin. See **Posting the review**.

Windows PowerShell 5.1 has no `&&` — chain commands with `;`. For `--branch` / `--pr` target mode, prefer `pwsh` (PowerShell 7+).

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

## CI / headless mode (no interactive prompts)

When `$AI_REVIEW_CI=1` (or `$CI=true`, set automatically by Bitbucket Pipelines, GitHub Actions, etc.) is present in the environment, override every `[y/n]` interaction in this file with its affirmative default:

- **Skip Step -1 (version check) entirely.** The container's installed version is fixed — there's no manual update path in CI. Print `↷ CI mode — skipping version check.` and continue.
- **Skip the Step 2 post-confirmation prompt.** Treat the answer as `y` and post the findings without asking.
- **Skip the Step 0.7 reply-confirmation prompt(s).** Take the analysed action without asking.
- **Skip the disk write in Step 4 (Learning summary).** Print the summary to stdout but do **not** append to `.ai-review/learning-log.md` — CI runners are ephemeral and may be shared across users; the personal log doesn't belong there.
- Narration unchanged — print every `🔍 / ✓ / ↷ / ⚠️` line so CI logs show what happened.

The CI wrapper is `.claude/skills/code-reviewer/bin/ai-review-ci`. Devs can set `AI_REVIEW_CI=1` locally to dry-run the CI flow before committing the pipeline yaml.

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

## Step 0.2 — Load card context (recommended)

Before analyzing the diff, fetch the linked issue-tracker card. The goal is to judge **whether the change solves the right problem** — not just whether the code itself is clean. A clean implementation of the wrong feature is still a defect.

1. **Find the ticket reference.** Look, in order, for a pattern like `[A-Z][A-Z0-9_]*-\d+` (Atlassian project key format — e.g. `B20-11233`, `PROJ-42`):
   - PR title (e.g. `B20-11233 - Add listing logic report`)
   - Source branch name (e.g. `feature/B20-11233-add-stats-...`)
   - PR description body

2. **Fetch the card.** Use the first available source — never block the run on this:
   - **Atlassian MCP** tools (`mcp__claude_ai_Atlassian__getJiraIssue`, `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql`) when configured. Preferred.
   - **PR description** body — read whatever the developer wrote inline.
   - **Branch name** — last resort; gives only the slugified card title.

3. **Read these fields when available:**
   - Title (the actual ask)
   - Description (the problem and constraints)
   - Acceptance criteria (what "done" means)
   - Type (bug / feature / refactor — informs review tone)
   - **Comments / discussion thread** (Atlassian MCP only — `getJiraIssue` returns or links the comments). Design decisions, reviewer suggestions, and constraints are often raised *after* the description is written and live only in the thread. Read them.

4. **Use this as reference context for Step 1, not as a new scope.** The Scope rule below is unchanged — you still review only what the diff touched. The card informs **judgment**:
   - Does the diff address the stated problem, or something adjacent?
   - Does it satisfy the explicit acceptance criteria?
   - Are obvious card requirements missing from the diff? (Surface as 🟡 Warning — likely incomplete work.)

4a. **File relatedness check — every changed file should plausibly belong to this task.** Once the card is loaded, list the changed files (`git diff --name-only <base>...HEAD`) and, for each, ask: *does this file's change serve the card's stated goal?* Flag any file with **no plausible connection** to the task as a 🟡 Warning, phrased as a request to confirm — not an accusation:

   > 🟡 `{path}` doesn't appear related to {TICKET} ({one-line task summary}). Confirm it belongs in this PR, or move it to its own branch — unrelated changes ride in unreviewed and muddy the diff.

   **Use judgement — a file that legitimately *supports* the task is related**, even if the card doesn't name it: the implementation files, the layers they call through (controller → service → repository → model), the view/component that surfaces the change, any config/migration they require, and the matching tests all count. Only flag files whose change has **no believable link** to the stated work — e.g. a stray formatting sweep, a leftover debug statement, a merge artifact, or an edit in a feature area the task never mentions.

   Skip this check entirely when no card context was obtained (step 5) — you can't judge relatedness without knowing the task.

4b. **Discussion-decision check — honour decisions raised in the ticket thread.** When the comments were read (Atlassian MCP), scan them for **concrete technical decisions or suggestions** — a recommended package, library, or approach; an architectural choice; a constraint (e.g. "must stay backward-compatible with the v1 endpoint"); or a "don't do X" steer. If the diff **contradicts or ignores** such a decision, flag it as a 🟡 Warning, phrased to confirm — not accuse:

   > 🟡 The {TICKET} discussion suggested **{decision}** ({commenter}, {date}), but the implementation appears to {do otherwise}. Confirm this was considered and intentionally not followed — if it was rejected, capture the reason on the ticket so it isn't re-raised.

   **Scope tightly — only flag a decision that is concrete, technical, and clearly unaddressed:**
   - It must be an actionable steer (a named library, pattern, endpoint, or explicit "do/don't"), not chit-chat, a question, "LGTM", or a status update.
   - A suggestion the diff *does* follow → say nothing.
   - A suggestion that was explicitly resolved in the thread ("agreed, we'll skip that because …") → respect that resolution; don't re-flag it.
   - You're surfacing for confirmation, not enforcing — the team may have a good reason. One Warning per ignored decision.

   Skip this check when comments weren't available (PR-body / branch-name fallback, or no MCP).

5. **No ticket detected** → print `No ticket reference detected — reviewing diff against develop only.` and continue. The skill still works without a card; it just loses the "right problem", file-relatedness, and discussion-decision signals.

6. **Read-only.** Never edit the card, post comments on it, transition its status, or write back any state.

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

- `CHECKPOINT_SHA` **non-empty AND equals `HEAD_SHA`** → there are no new commits to analyze. Developer replies are independent of new commits, so **first run Step 0.7 (respond to developer replies) below**, then **stop** — do not run scoping, the Step 1 analysis, or Step 2 posting. After handling any replies, print exactly this and stop:

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

## Step 0.7 — Respond to developer replies

Developers can reply to a finding's comment thread on the PR to push back, ask a question, or say they've fixed it. Check for replies the bot hasn't answered yet:

```bash
.claude/skills/code-reviewer/scripts/check_replies.py
```

This outputs a JSON array of **open** findings whose thread ends with an unanswered developer reply. Each entry carries `root_id` (the finding comment), `reply_id` (the developer message to reply under), `path`, `line`, `posted_sha`, `problem`, `finding_body`, `reply_text`, `reply_author`, and the full ordered `thread`. **If the array is empty, skip to the Workflow.**

For each entry, gather context, then judge the reply on its merits:

1. Read the developer's `reply_text` (and the full `thread` when there's more than one message).
2. Read the current code at `{path}:{line}` in the working tree (in target mode, read `$WORKTREE/{path}`).
3. Re-read the original `problem` / `finding_body`.
4. **Pick exactly one response type:**

   | The reply is… | Response | Side effect (on confirm) |
   |---|---|---|
   | **A correct objection** — false positive, or acceptable given context you can verify | **Concede** — briefly agree and say you're dismissing it | Dismiss the finding |
   | **A wrong or weak objection** — the finding still stands | **Hold** — explain *why* it still matters, answering their specific point (not a restatement) | none |
   | **A question** | **Answer** in plain language | none |
   | **"I fixed it"** | **Verify** against the current code (same judgement as Step 0.5). Genuinely addressed → confirm; not addressed → explain what's still outstanding (treat as Hold) | Resolve the finding when truly fixed |
   | **Ambiguous / not a substantive objection** | **Answer** briefly | none — do **not** dismiss or resolve |

   Concede when the developer is right — conceding gracefully builds trust. Hold only with a concrete reason. Keep every reply short, plain, and specific to what they said; never re-paste the whole original finding; never assign blame.

5. Draft each reply as plain markdown — no severity prefix, no five-section finding structure. This is a conversation, not a new finding.

Then print a summary and ask for confirmation:

> {N} developer repl(y/ies) awaiting a response on PR #{ID}:
> - `{path}:{line}` — {concede | hold | answer | confirm fix}
>
> Post these replies? [y/n]

**n** → skip replying and continue to the Workflow.

**y** → for each entry, post the reply (threaded under the developer's message), then apply its side effect:

```bash
.claude/skills/code-reviewer/scripts/post_reply.py --parent-id={reply_id} <<'REPLY'
{your drafted reply}
REPLY
```

- **Concede** → also dismiss the finding so future runs don't re-flag it:
  ```bash
  .claude/skills/code-reviewer/bin/ai-review dismiss --comment-id={root_id} --reason="{one line on why you conceded}"
  ```
- **Confirm fix** → find the commit that addressed it (as in Step 0.5: `git log --oneline {posted_sha}..HEAD -- {path}`, take the last line) and mark it resolved:
  ```bash
  .claude/skills/code-reviewer/scripts/update_resolved.py --comment-id={root_id} --fix-sha={fix_sha}
  ```

`post_reply.py` appends a hidden `<!-- ai-review:reply -->` marker so the bot recognises its own answer and never replies to it again. **Windows mode:** pipe the body into `python .claude/skills/code-reviewer/scripts/post_reply.py --parent-id={reply_id}` with a here-string.

Print a summary before continuing:
> Responded to {N} repl(y/ies): {a} conceded, {b} held, {c} answered, {d} resolved.

---

## Workflow

### Narration — show the run, don't run it silently

Before invoking each script in Steps -1 → 0.7 and the scoping scripts in Step 1, print a one-line header naming the step in plain language (e.g. `Step 0.5 — Checking previously posted comments`). After each script returns, **always relay the script's own progress lines** (the `🔍 / ✓ / ↷ / ⚠️` messages it prints to stdout/stderr) — never swallow them. End each step with a one-line outcome summary so the developer can follow the run without reading raw script output. Quiet success is a regression — every step must produce at least one visible line.

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

1. Print a summary and ask for confirmation (this and the Step 0.7 reply confirmation are the only interactive prompts in the run):

   > Found **{N} issues** ({X} critical, {Y} warnings, {Z} suggestions) on branch `{branch}`.
   > Post to PR #{ID}? [y/n]

2. **y** → post all findings as inline Bitbucket PR comments (see **Posting the review** below).
3. **n** → end here. Print: `Skipped. Run /code-reviewer again to post, or use /code-fixer to fix locally.`

Do not run any Bitbucket posting scripts until the user confirms **y**.

---

### Step 3 — Sync Jira card status (idempotent, soft-fails)

After all the comment-state work in Steps 0.5 / 0.6 / 2 is done, transition the linked Jira card based on the **current state of the PR** — not just what this run produced. A clean diff or a fully-addressed PR should move the card back to `Code Review`; remaining open findings should move it to `Failed Code Review`.

1. **Compute `has_open_findings`** — `true` if any of:
   - This run posted ≥1 new finding (and the user said `y`).
   - There are pre-existing open findings from prior runs that weren't marked resolved this run (i.e. `check_resolved.py`'s output minus what Step 0.5 just resolved).
   - **Dismissed findings do NOT count as open** — they're explicit accepts.

   Otherwise → `false` (clean PR, or all findings now resolved/dismissed).

2. **Run:**

   ```bash
   .claude/skills/code-reviewer/scripts/update_card_status.py \
       --has-open-findings={true|false}
   ```

   The script:
   - Auto-detects the ticket key from the current branch (regex `[A-Z][A-Z0-9_]*-\d+`); pass `--ticket=KEY` to override.
   - Reads `JIRA_BASE_URL`, `JIRA_EMAIL` (falls back to `BITBUCKET_EMAIL`), `JIRA_API_TOKEN` (falls back to `BITBUCKET_API_TOKEN`).
   - Fetches the issue's current status. No-op if already correct.
   - Finds the transition whose target matches the desired status — defaults: `Failed Code Review` (findings exist) or `Code Review` (clean / all-addressed). Override per-repo via `JIRA_FAILED_STATUS` / `JIRA_PASSED_STATUS`.
   - POSTs the transition.

3. **Soft-fail everywhere.** Missing creds, no JIRA key in branch name, workflow doesn't expose the needed transition — the script prints a `↷ skipped` reason to stderr and exits 0. The review run never fails because of Jira sync.

4. Relay the script's output verbatim per the narration rule.

---

### Step 4 — Learning summary (private — author only, never posted)

After the review is posted (or skipped), generate a short learning summary for the developer who ran the skill. This is a **private artefact** — it exists to help the author stay sharp while the bot does the review work. It must **never** appear on Bitbucket, never be folded into the disclaimer, never be attached to a finding comment, never be emailed, never be exposed in any channel that another person sees.

**Output exactly two places:**
1. Print to the terminal (stderr is fine) so the author sees it at end of run.
2. Append to `.ai-review/learning-log.md` (the directory is gitignored — verify before writing). Create the file if missing; never overwrite a previous entry.

**Template (use this exact section order; one log entry per run):**

```
─── 📚 Learning summary — PR #{PR_ID} / {branch} ───
Findings: {N} ({X} critical, {Y} warnings, {Z} suggestions)

Dimensions exercised (most → least):
  • §{n} {dimension name} ×{count}
  ...

Recurring patterns this run:
  • {one-line pattern that spans 2+ findings, with `path:line` refs}
  ...
  (if no recurring pattern: `• No repeated pattern this run.`)

Concepts worth re-reading before your next session:
  • §{n} {dimension name} — {one-line concept reminder}
  ...
  (cap at 3; pick the dimensions that fired most often or most severely)

Saved to .ai-review/learning-log.md
```

**Synthesis rules:**
- Group by **pattern**, not by file. Inline comments already cover per-file detail; this section's job is to surface the *theme* across findings.
- A "recurring pattern" needs at least 2 findings of the same dimension OR the same root cause across different dimensions.
- The "concepts" list is a teaching tool — write each as a single sentence the author can quote from memory next time.
- Skip the summary entirely if 0 findings, but still append a log entry: `─── 📚 No findings on PR #{PR_ID} — clean diff. ───`.

**Log file header (only when creating the file for the first time):**

```markdown
# AI review — personal learning log

Private notes synthesised from each `/code-reviewer` run. Gitignored, never posted.
```

Each run appends a new dated entry with the timestamp + the template above, separated by `---`.

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

#### 1. The problem
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
2. Compile all findings into a JSON array and write it to `.ai-review/findings.json` as UTF-8. Each entry needs:
   - `path`, `line` — where the issue lives
   - `body` — the full five-section comment including the auto-fix command with `{COMMENT_ID}` as a placeholder
   - `dim` — the dimension code from the Review lens (e.g. `"3a"`, `"4b"`, `"12"`). Used for telemetry.
   - `severity` — `"critical"`, `"warning"`, or `"suggestion"` (lowercase). Used for telemetry.

   Example `.ai-review/findings.json`:
   ```json
   [
     {
       "path": "app/Http/Controllers/UserController.php",
       "line": 22,
       "body": "🔴 **Critical** — ...\n\n### 1. The problem\n...",
       "dim": "3b",
       "severity": "critical"
     }
   ]
   ```
3. Post via `post_review`, passing the findings-file path (the script resolves `{COMMENT_ID}` and embeds the telemetry marker after posting). Writing findings to a UTF-8 file — rather than piping a here-string — sidesteps shell quoting and the Windows console code page, which can otherwise turn emoji / em-dashes into mojibake. Both scripts also still accept the JSON array on stdin as a fallback.

**Unix mode:**
```bash
.claude/skills/code-reviewer/scripts/post_review.sh .ai-review/findings.json
```

**Windows mode:**
```powershell
pwsh .claude/skills/code-reviewer/scripts/post_review.ps1 .ai-review/findings.json
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

Each `.sh` script below has a matching `.ps1` Windows variant (same name, same arguments, same `.ai-review/target.json` handling). Use the variant selected by **OS detection** above. The `.py` scripts run on both platforms via `python`/`python3`.

- **`branch_summary.sh [base]`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py [--base REF] [--no-snippets]`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`post_review.sh`** — posts the compiled review as inline Bitbucket PR comments. Reads findings from a JSON file path (first arg, preferred) or stdin. Requires `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` env vars.
- **`check_replies.py`** — prints a JSON array of open findings whose thread ends with an unanswered developer reply (see Step 0.7). Empty `[]` when nothing awaits a response.
- **`post_reply.py --parent-id=<ID>`** — posts a threaded reply (body on stdin) under a PR comment and tags it with a hidden `ai-review:reply` marker so the bot won't answer its own reply.
- **`setup_target.sh --branch=<name>|--pr=<N>`** — fetches a branch and creates a detached git worktree for reviewing without checkout. Writes `.ai-review/target.json` inside the worktree. Prints the worktree path to stdout.
- **`cleanup_target.sh <worktree-path>`** — removes a worktree created by `setup_target.sh`.
