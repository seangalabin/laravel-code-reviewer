---
name: code-fixer
description: Diff-scoped code review and interactive fix applicator for the current branch. Reviews ONLY lines changed since develop, then walks you through applying fixes locally. No Bitbucket posting.
---

# Code Fixer

Reviews the **current branch's changes** against the base branch (`develop` by default; override with the `AI_REVIEW_BASE_BRANCH` env var for a repo whose integration branch is `master` or similar). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## Model guard (first, before anything else)

This skill runs on **Sonnet or Opus only**. Check which model you are before OS detection, before reading any file, before running any script.

If you are **neither** Sonnet nor Opus — Fable, Haiku, or anything else — stop immediately and print exactly:

```
ERROR: code-fixer only runs on Sonnet or Opus.
Run /model sonnet and re-invoke this skill.
```

Then end the turn. Do not review, do not scope the diff, do not apply any fix, do not offer to continue on the current model, and do not work around the guard by delegating the review to a Sonnet subagent — the arbitration in Step 7 happens in the main context, so the main context itself must be Sonnet or Opus.

---

## OS detection (once, before Step 1)

Follow these steps in order — stop as soon as one succeeds:

**Step A.** Run `uname -s`.
- Returns `Linux` → use `.sh` scripts (Linux / WSL).
- Returns `Darwin` → use `.sh` scripts (macOS).
- Returns a value starting with `MINGW` or `CYGWIN` → use `.sh` scripts (Git Bash on Windows; bash is available).
- Errors or returns anything else → go to Step B.

**Step B.** Run `python3 -c "import platform; print(platform.system())"` (or `python` if `python3` is unavailable).
- Returns `Linux` or `Darwin` → use `.sh` scripts.
- Returns `Windows` → use `.ps1` scripts.
- Errors → go to Step C.

**Step C.** Assume Windows. Use `.ps1` scripts and print:
> ⚠️ OS could not be detected — assuming Windows and using `.ps1` scripts.

**PowerShell version fallback (Windows only):** try `pwsh` (PowerShell Core 7+) first. If `pwsh` is not found, fall back to `powershell` (Windows PowerShell 5.1).

## Requirements check (once, after OS detection)

Check for soft dependencies and note what gets skipped if any are absent. Missing tools are **not fatal** — the skill continues with reduced capability.

| Tool | Unix/Mac check | Windows check | If missing |
|---|---|---|---|
| Python | `python3 --version 2>/dev/null \|\| python --version 2>/dev/null` | `python --version 2>/dev/null` | Skip `scan_diff.py` pre-pass |
| PHP | `php --version 2>/dev/null` | `php --version 2>/dev/null` | Skip pint and pest in the fix loop |
| `vendor/bin/pint` | `test -f vendor/bin/pint` | `Test-Path vendor/bin/pint` | Skip pint check in the fix loop |
| `vendor/bin/pest` | `test -f vendor/bin/pest` | `Test-Path vendor/bin/pest` | Skip pest check in the fix loop |

Print one warning per missing tool before proceeding:

> ⚠️ `<tool>` not found — `<what will be skipped>` will be skipped.

Then carry the results forward — every affected step re-checks this before running rather than failing mid-loop.

---

## Step 1 — Version check (always first, before anything else)

**Unix/Mac:**
```bash
.claude/skills/code-fixer/scripts/check_version.sh
```
**Windows:**
```powershell
pwsh .claude/skills/code-fixer/scripts/check_version.ps1
```

- Exit **0** → continue normally.
- Exit **1** → print the script's output, then ask:

  > Update now? [y/n]

  **y** → run the update:
  ```bash
  npx github:seangalabin/laravel-code-reviewer --skill=fixer
  ```
  Then stop. Print: `Updated. Run /code-fixer again to use the latest version.`

  **n** → stop. Print: `Skipped. Run /code-fixer again after updating.`

---

## Global constraints

These apply in all modes and cannot be overridden by project config:

- **Never auto-commit.** Apply or post findings only — never run `git commit`, `git push`, or any destructive git operation.
- **Refuse on protected branches.** If the current branch is `main`, `master`, or `develop`, stop immediately: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`
- **Single agent, always.** Never use the Task/Agent tool or spawn subagents for any part of the run — analysis, scoping, reading, or applying fixes. Every step happens in this context; delegation multiplies token cost without improving judgment.

---

## Step 2 — Check for project-specific overrides (optional)

**Company standards live in the project's `CLAUDE.md`.** If the project root has a `CLAUDE.md`, read it and apply its conventions and rules **in addition to** the built-in lens below. These are first-class:

- A company rule takes **precedence** over a built-in rule when they conflict.
- A company rule may **disable** a built-in dimension (e.g. "Disable dimension 6") — honour that and skip the built-in check.
- Apply company rules at the severity they state; where a convention is stated without a severity, treat a violation as 🟡 Warning.

Also honour, if present: `.cursorrules` / `.github/copilot-instructions.md`. Do **not** read `.coderabbit.yaml` or `.claude/code-review-rules.md` — CLAUDE.md is the single source for company rules.

If none exist, skip this step. The skill's built-in rules are reasonable Laravel defaults and work standalone.

---

## Step 3 — Load card context (recommended)

Before analyzing, fetch the linked issue-tracker card so the lens evaluates your branch against the actual ask — not just whether the code is clean. You're auditing your own work; the card tells you whether you finished it.

1. **Find the ticket reference.** Look, in order, for a pattern like `[A-Z][A-Z0-9_]*-\d+` (Atlassian project key format — e.g. `B20-11233`, `PROJ-42`):
   - Current branch name (e.g. `feature/B20-11233-add-stats-...`)
   - Recent commit subjects on the branch (`git log --format=%s "origin/${AI_REVIEW_BASE_BRANCH:-develop}..HEAD"`)

2. **Fetch the card.** Use the first available source — never block the run on this:
   - **Atlassian MCP** tools (`mcp__claude_ai_Atlassian__getJiraIssue`, `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql`) when configured. Preferred.
   - **Branch name** — last resort; gives only the slugified card title.

3. **Read these fields when available:** Title, Description, Acceptance criteria, Type (bug / feature / refactor), and the **comments / discussion thread** (Atlassian MCP only — design decisions and reviewer suggestions are often raised after the description and live only in the thread).

4. **Use this as reference context for Step 4, not as a new scope.** The Scope rule below is unchanged — you still review only what the branch touched. The card informs **judgment**:
   - Does the branch address the stated problem?
   - Does it satisfy the explicit acceptance criteria? (Missing requirements → 🟡 Warning.)

4a. **File relatedness check — every changed file should plausibly belong to this task.** List the changed files (`git diff --name-only "origin/${AI_REVIEW_BASE_BRANCH:-develop}...HEAD"`) and, for each, ask: *does this file's change serve the card's stated goal?* Flag any file with **no plausible connection** as a 🟡 Warning, phrased to confirm — not accuse:

   > 🟡 `{path}` doesn't appear related to {TICKET} ({one-line task summary}). Confirm it belongs on this branch, or move it out — unrelated changes ride in unreviewed and muddy the diff.

   **Use judgement — a file that legitimately *supports* the task is related**, even if the card doesn't name it: the implementation files, the layers they call through, the view/component that surfaces the change, any config/migration they require, and the matching tests all count. Only flag files whose change has **no believable link** to the stated work — a stray formatting sweep, a leftover debug statement, a merge artifact, or an edit in a feature area the task never mentions. Skip this check when no card context was obtained (step 5).

4b. **Discussion-decision check — honour decisions raised in the ticket thread.** When the comments were read (Atlassian MCP), scan them for a **concrete technical decision or suggestion** — a recommended package, library, or approach; an architectural choice; a constraint; or a "don't do X" steer. If the branch **contradicts or ignores** it, flag a 🟡 Warning, phrased to confirm:

   > 🟡 The {TICKET} discussion suggested **{decision}** ({commenter}), but the branch appears to {do otherwise}. Confirm it was considered — if intentionally rejected, capture the reason on the ticket.

   Scope tightly: only an actionable, technical, clearly-unaddressed steer (named library / pattern / explicit do-don't) — not chit-chat, questions, or "LGTM". If the branch follows it, or the thread already resolved it ("agreed, skip that because …"), say nothing. Skip when comments weren't available.

3c. **Implementation context.** Running in your own session, you usually already have the "why" behind the change. If a rationale block exists in the card (a comment, or a section marked `<!-- ai-review:context -->` — decisions, assumptions, trade-offs), weigh it the same disciplined way as `/code-reviewer` does: it explains intent so you don't flag a deliberate trade-off, but it does **not** waive a genuine defect (a 🔴 stands), a flawed rationale is still challenged, and findings anchor to the actual code. This is also the place to *capture* that rationale for the reviewer — paste it as **inline text** (markdown or plain) into the PR description or a card comment so the reviewer inherits your context. Don't attach it as a file — the reviewer reads comment/PR text, it can't download attachments.

5. **No ticket detected** → print `No ticket reference detected — auditing branch against the base branch only.` and continue.

6. **Read-only.** Never edit the card, post comments on it, or transition its status.

---

## Scope rule (read this before touching files)

**Review only what the branch changed.** That means:

- Added or modified lines in the diff — fair game, always.
- Deleted lines — fair game if the deletion introduces a regression or removes a guard.
- Pre-existing lines **inside a touched hunk** — fair game when the surrounding change makes them newly relevant.
- Pre-existing lines **outside any hunk, in a file the branch did not touch** — out of scope. Do not surface.
- Files the branch did not touch — out of scope. Do not open them looking for issues.

When a pre-existing issue is in a touched hunk, label it `(pre-existing, but touched)`.

**Reading existing code for context is allowed; *flagging* it is not.** You may open untouched files to understand how the change fits — a called Service, a sibling class, an existing interface or Repository — and the **architecture/consistency dimensions (§1, incl. §1c Repository granularity and §1g OOP structure) require it**: a duplication or missing-contract smell only shows when the new code is compared to what already exists. The rule is about *where the finding lands*, not what you may read: **anchor every finding to the changed lines** ("this **new** class duplicates the existing X — extract a shared contract"), never to a pre-existing problem inside an untouched file.

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

### Refresh the base branch first

The base branch defaults to `develop`; set `AI_REVIEW_BASE_BRANCH` (e.g. `master`) to audit a repo whose integration branch is something else. Print `🔍 Refreshing the base branch...` then run:

```bash
git fetch origin "${AI_REVIEW_BASE_BRANCH:-develop}"
```

The review is diffed against `origin/${AI_REVIEW_BASE_BRANCH:-develop}`. A stale remote-tracking ref means the diff base is wrong.

- Success → print `  ✓ base branch up to date.` and continue.
- Failure (offline, no remote, etc.) → print `  ↷ Couldn't refresh the base branch — reviewing against your local copy.` and continue. A missing fetch is not fatal; the local copy is still usable.

### Run the scoping scripts

Run these up-front to anchor the review:

**Unix/Mac:**
```bash
.claude/skills/code-fixer/scripts/branch_summary.sh    # what changed: file counts, commits, base ref
python3 .claude/skills/code-fixer/scripts/scan_diff.py # pre-pass: pattern matches for mechanical red flags
```
**Windows:**
```powershell
pwsh .claude/skills/code-fixer/scripts/branch_summary.ps1
python .claude/skills/code-fixer/scripts/scan_diff.py
```

If Python was not found in the requirements check, skip `scan_diff.py` entirely and print:
> ⚠️ `scan_diff.py` skipped — Python not available. Proceeding with manual review only.

Then read the full diff:

```bash
git diff "origin/${AI_REVIEW_BASE_BRANCH:-develop}...HEAD"    # source of truth for scope
```

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter.

---

## Workflow

### Narration — show the run, don't run it silently

Before invoking each script in Steps -1 → 0.1 and the scoping scripts in Step 4, print a one-line header naming the step in plain language (e.g. `Step 1 — Checking skill version`). After each script returns, **always relay the script's own progress lines** (the `🔍 / ✓ / ↷ / ⚠️` messages it prints to stdout/stderr) — never swallow them. End each step with a one-line outcome summary so the developer can follow the run. Quiet success is a regression — every step must produce at least one visible line.

### Step 4 — Analyze

1. **Load project rules** (Step 2 above).
2. **Refuse if on a protected branch.** Run `git branch --show-current`. If it returns `main`, `master`, or `develop`, stop: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`
3. **Diff first.** Run the scoping scripts and read every hunk. Do not start by reading whole files.
4. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — findings on those files are out of scope unless changed.
5. **Single-context analysis — never spawn subagents.** The entire review runs in this context: do **not** use the Task/Agent tool or delegate any slice of the analysis to a subagent, regardless of diff size — fan-out multiplies token cost for no judgment gain. Count the diff's changed lines for narration and chunking (`git diff --shortstat "origin/${AI_REVIEW_BASE_BRANCH:-develop}...HEAD"`). The `scan_diff.py` pre-pass output from the scoping step is Phase 1 input to item 7; if it failed or was skipped (no Python), continue — the lens walk still runs; note `scan: skipped` in the ledger.

6. **Lens walk.** Apply the full review lens dimension by dimension — do not free-associate. Walk the lens in order and, for **each** numbered dimension (§1 Architecture → §16 Scalability) plus the company rules from Step 2, deliberately check the diff against that dimension before moving on. A dimension is only "done" once you've recorded a finding or confirmed the diff is clean for it. **Large diffs (roughly 300+ changed lines or 10+ files): chunk by file group** — walk related files together (a feature's controller + service + tests), complete the full lens per group, then merge the per-group results into one ledger; never trim the lens to save context. Then run a completeness-critic pass: re-scan the diff once more focused only on dimensions you marked clean — "genuinely fine, or did I skim?" Watch the easily-missed: §2i magic literals, §2m `count()` emptiness, §2p name-matches-behaviour, §3i hardcoded secrets, §4b N+1, §10 `report()` on caught exceptions. Ledger `Source` column: `inline`.

7. **Arbitrate.**
   - **Adjudicate every `scan_diff.py` line.** Each pre-pass hit must end as either a confirmed finding or a rejection with a stated reason (e.g. "env() hit is in config/ — exempt", "print_r has `true` second arg into Log — exempt"). Silent drops are forbidden; if the pre-pass printed 12 hits, your arbitration must account for 12.
   - **Dedup findings.** Same file, same dimension, lines within ±5 → keep the more specific / higher-severity finding. Where a lens-walk finding duplicates a confirmed pre-pass hit, keep one (the better-worded).
   - Re-check each surviving finding's severity against the lens — the lens severity wins.
   - **Build the coverage ledger v2** — one row per dimension with its source:

     | Dim | Status | Source |
     |---|---|---|
     | §1 Architecture & layering | ✓ 2 findings | inline |
     | §2 Code standards | ✓ clean | inline |
     | §3 Security | ✓ 1 finding | inline + scan |
     | §15 Blade | n/a — no Blade files changed | — |

     `n/a` only when no changed file is in that dimension's scope. Every dimension must appear.

8. **Compile all findings** grouped by severity (🔴 Critical → 🟡 Warning → 🔵 Suggestion). Do not modify any files yet.

Print the coverage ledger v2 (with Source column), then a brief summary once analysis is done:

> Found **{N} issues** ({X} critical, {Y} warnings, {Z} suggestions). Starting fix loop.

### Step 5 — Pre-flight checks

Run these before touching any file:

1. Refuse if branch is `main`, `master`, or `develop` (already caught in Step 4).
2. Run `git status --short`. If the working tree has uncommitted changes, ask:
   > Working tree has uncommitted changes. Apply fixes anyway? [y/N]
   Default is **no** — stop unless the user explicitly types `y`.
3. Count files affected by the planned fixes. If more than 20, list the files and ask:
   > {N} files would be modified. This is above the 20-file safety limit. Proceed anyway? [y/N]
   Default is **no** — stop unless the user explicitly confirms.

### Step 6 — Fix loop

Work through findings in Critical → Warning → Suggestion order.

For each issue:
1. Print the issue (see Per-issue comment structure below).
2. Ask:
   > Apply this fix? [y/n/s/q]
   - `y` — apply the diff to the file, confirm with `✓ Fixed {file}:{line}`
   - `n` — skip this issue
   - `s` — skip all remaining issues of this severity level
   - `q` — quit the loop now, keep all fixes already applied

3. When `y` is chosen, apply the diff and append to `.ai-review/applied-{timestamp}.log`:
   ```
   File: {path}:{line}
   Prompt:
   {ai-fix-prompt text}

   Diff applied:
   {diff}
   ```

4. **Verify the fix before moving on.** Right after each applied fix, run the checks scoped to the changed files:

   **Unix/Mac:**
   ```bash
   .claude/skills/code-fixer/scripts/pint_changed.sh       # PHP formatting (check only)
   .claude/skills/code-fixer/scripts/pest_for_changed.sh   # tests mapped to changed files
   ```
   **Windows:**
   ```powershell
   pwsh .claude/skills/code-fixer/scripts/pint_changed.ps1
   pwsh .claude/skills/code-fixer/scripts/pest_for_changed.ps1
   ```
   If the fix touched a `.js`, `.ts`, or `.vue` file **and** the project's `package.json` defines a `lint` script, also run:
   ```bash
   npm run lint
   ```
   - All pass → print `✓ Verified — pint, pest, lint clean.` and continue to the next issue.
   - Any fail → print the failing output and warn: `⚠️  Verification failed after this fix. Review before continuing (press q to stop and inspect).` Do **not** auto-stage or auto-commit anything to silence a failure.

   Skip a check cleanly when it doesn't apply:
   - The scoped scripts already print "No PHP changes" and exit 0 when nothing matches.
   - Skip `pint_changed` if PHP or `vendor/bin/pint` was not found in the requirements check — print `⚠️ pint skipped (not available).`
   - Skip `pest_for_changed` if PHP or `vendor/bin/pest` was not found — print `⚠️ pest skipped (not available).`
   - Skip `npm run lint` entirely when no JS/Vue/TS changed, no `lint` script exists in `package.json`, or `node_modules/` is absent.

**End of loop — print summary:**

```
Applied {N} fix(es), skipped {M}.
Modified files:
  - {file1}
  - {file2}
Verification: {pint/pest/lint status of the last run}
Run the full suite before pushing.
```

### Step 7 — Learning summary (private — author only, never posted)

After the fix loop ends, generate a short learning summary for the developer who ran the skill. This is a **private artefact** — it exists to help the author stay sharp while the bot does the review work. It must **never** appear on Bitbucket, never be folded into a posted comment, never be attached to any external surface — this is `code-fixer`, which is local-only by design, and the summary stays local too.

**Output exactly two places:**
1. Print to the terminal so the author sees it at end of run.
2. Append to `.ai-review/learning-log.md` (the directory is gitignored — verify before writing). Create the file if missing; never overwrite a previous entry.

**Template (same shape as `/code-reviewer`'s Step 6 — keep these in lockstep):**

```
─── 📚 Learning summary — {branch} (local fix loop) ───
Findings analysed: {N} ({X} critical, {Y} warnings, {Z} suggestions)
Applied: {A}  ·  Skipped: {S}

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
- Group by **pattern**, not by file. Per-finding detail is already in the applied-fixes log; this section's job is to surface the *theme*.
- A "recurring pattern" needs at least 2 findings of the same dimension OR the same root cause across different dimensions.
- The "concepts" list is a teaching tool — write each as a single sentence the author can quote from memory next time.
- Skip the summary entirely if 0 findings, but still append a log entry: `─── 📚 No findings on {branch} — clean diff. ───`.

**Log file header** (only when creating the file for the first time):

```markdown
# AI review — personal learning log

Private notes synthesised from each `/code-reviewer` and `/code-fixer` run. Gitignored, never posted.
```

Each run appends a new dated entry with the timestamp + the template above, separated by `---`.

---

<!-- include:src/review-lens.md -->
## Output format

### Global rules

- **Plain language only.** Explain issues like you're talking to a junior dev on their first week. No jargon unless you immediately define it. Prefer "this runs the database query inside a loop, which is slow" over "N+1 query antipattern detected."
- **One issue per comment.** Do not bundle multiple problems into a single comment.
- **Be concrete.** Reference the actual variable, method, or line — not abstract concepts.

### Required opening message

🔧 **Code Fixer — review your changes are correct before committing**

### Per-issue comment structure

Each issue must contain sections 1–4 below, in this exact order, with these exact headings. Section 5 (the Pest test) is **conditional** — include it only when the fix changes behaviour.

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

#### 5. Suggested Pest test
Include this section **only when the fix changes behaviour** — a bug fix, a security/authorization change, new business logic, a data-integrity guard, or an API contract change. Provide a Pest test that would fail before the fix and pass after it.

**Skip this section entirely** for pure-style fixes (formatting, naming, readability, type hints, missing `strict_types`) — they don't change behaviour, so a test adds noise.

- Place the test at the path the project's convention implies (e.g. `app/Services/OrderService.php` → `tests/Feature/Services/OrderServiceTest.php`).
- If a matching test file already exists, show the new `it()`/`test()` block to add rather than a whole new file.
- Wrap it in a ` ```php ` block.

```php
it('loads order items in a single query', function () {
    $order = Order::factory()->has(OrderItem::factory()->count(3))->create();

    DB::enableQueryLog();
    app(OrderService::class)->calculateTotals(collect([$order]));

    expect(DB::getQueryLog())->toHaveCount(1);
});
```

### Severity tagging

Prefix each comment's title with one of:
- 🔴 **Critical** — bug, security issue, data loss risk. Creates a blocking task.
- 🟡 **Warning** — likely problem, performance, maintainability. Non-blocking.
- 🔵 **Suggestion** — style, readability, minor improvement. Optional.

---

## What not to do

- Don't comment on style issues already caught by the linter (Pint, ESLint).
- Don't open untouched files to look for new issues.
- Don't grade the whole architecture from a small change.
- Don't flag issues caught by Pint or the Pest ArchitectureTest as *findings* — they're CI's job. (You still **run** Pint/Pest/lint to verify each applied fix, per Step 6.4 — that's verification, not a finding.)
- Don't invent issues to fill buckets. An empty 🔴/🟡 list is a valid and welcome outcome.
- Don't suggest rewrites of working code unless there's a concrete reason.
- Don't say "consider" or "you might want to" — be direct: "this will fail when X" or "this is fine, but Y is faster."
- Don't repeat the same issue across multiple lines. Comment once on the first occurrence and mention "same pattern appears at lines X, Y, Z."
- Don't reference the original codebase author or assign blame.
- Don't auto-commit, push, or stage any files. Ever.

---

## Scripts

Each script has a Unix (`.sh`) and Windows (`.ps1`) variant. Use whichever matches the OS detected at startup.

| Script | Unix/Mac | Windows |
|---|---|---|
| Branch summary | `branch_summary.sh [base]` | `branch_summary.ps1 [base]` |
| Pattern scanner | `python3 scan_diff.py [--base REF] [--no-snippets]` | `python scan_diff.py [--base REF] [--no-snippets]` |
| Pint (check) | `pint_changed.sh` | `pint_changed.ps1` |
| Pint (fix+stage) | `pint_changed.sh --fix` | `pint_changed.ps1 -Fix` |
| Pest (scoped) | `pest_for_changed.sh [pest args]` | `pest_for_changed.ps1 [pest args]` |
| Version check | `check_version.sh` | `check_version.ps1` |

- **`branch_summary`** — one-glance overview of what changed vs the base branch (`origin/develop` by default, or `AI_REVIEW_BASE_BRANCH`).
- **`scan_diff.py`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`pint_changed`** — run Pint against changed PHP files. Check-only by default; the fixer uses check-only (never auto-stages).
- **`pest_for_changed`** — run only the Pest tests that map to changed files (`app/Foo/Bar.php` → `tests/Feature/Foo/BarTest.php`).
