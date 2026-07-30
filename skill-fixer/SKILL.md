---
name: code-fixer
description: Diff-scoped code review and interactive fix applicator for the current branch. Reviews ONLY lines changed since develop, then walks you through applying fixes locally. No Bitbucket posting.
---

# Code Fixer

Reviews the **current branch's changes** against the base branch (`develop` by default; override with the `AI_REVIEW_BASE_BRANCH` env var for a repo whose integration branch is `master` or similar). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

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
5. **Choose the analysis mode.** Count the diff's changed lines: `git diff --shortstat "origin/${AI_REVIEW_BASE_BRANCH:-develop}...HEAD"` insertions + deletions. **Under 25 changed lines** → run the *inline walk* described in 6a. **25 or more** → run the *fan-out* described in 6b. Either way, the `scan_diff.py` pre-pass output from the scoping step is Phase 1 input to item 7. If the `scan_diff.py` pre-pass failed or was skipped (no Python), continue — Phase 2/the inline walk still runs; note `scan: skipped` in the ledger.

6a. **Inline walk (small diffs).** Apply the full review lens dimension by dimension — do not free-associate. Walk the lens in order and, for **each** numbered dimension (§1 Architecture → §16 Scalability) plus the company rules from Step 2, deliberately check the diff against that dimension before moving on. A dimension is only "done" once you've recorded a finding or confirmed the diff is clean for it. Then run a completeness-critic pass: re-scan the diff once more focused only on dimensions you marked clean — "genuinely fine, or did I skim?" Watch the easily-missed: §2i magic literals, §2m `count()` emptiness, §2p name-matches-behaviour, §3i hardcoded secrets, §4b N+1, §10 `report()` on caught exceptions. Ledger `Source` column: `inline`.

6b. **Fan-out (25+ changed lines).** Launch **six parallel read-only subagents** with the Task/Agent tool, one per lens slice:

   | Slice | Dimensions | Skip when |
   |---|---|---|
   | S1 | §1 Architecture, §4 Laravel, §5 Models | — |
   | S2 | §3 Security, §7 Correctness, §8 Data integrity | — |
   | S3 | §2 Standards & readability | — |
   | S4 | §9 Performance, §10 Error handling, §16 Scalability | — |
   | S5 | §12 Front-end, §15 Blade | no JS/TS/Vue/Blade file in the diff |
   | S6 | §6 Enums, §11 Migrations, §13 Testing, §14 API design | mark individual dims n/a when no file in scope |

   Each subagent prompt MUST contain, verbatim where applicable:
   - the working directory and the changed-file list;
   - the instruction: *"Read the diff hunks first (`git diff {BASE}...HEAD -- {files}`); read surrounding code only for context. Findings are only valid on changed lines or their direct blast radius."*;
   - **only that slice's lens sections**, copied from this skill's lens below, plus any project CLAUDE.md rules touching those dimensions;
   - the implementation-context block from Step 3c if one exists, with the discipline: context may downgrade style-level doubts, it never dismisses a 🔴;
   - the output contract: *"Return ONLY a JSON array of findings `[{file, line, dim, severity, title, body}]` followed by a ledger line per dimension: `§N <name> — ✓ clean | ✓ K findings | n/a — no files in scope`. No prose."*
   - the constraint: read-only — no edits, no posting, no writes, and do **not** read `.ai-review/dismissals.json` (dismissal filtering happens in the main context).

   If the Agent tool is unavailable or a slice agent errors, **fall back to the inline walk (6a) for that slice's dimensions only** and mark its ledger rows `inline fallback`.

7. **Arbitrate (main context is the judge).**
   - **Adjudicate every `scan_diff.py` line.** Each pre-pass hit must end as either a confirmed finding or a rejection with a stated reason (e.g. "env() hit is in config/ — exempt", "print_r has `true` second arg into Log — exempt"). Silent drops are forbidden; if the pre-pass printed 12 hits, your arbitration must account for 12.
   - **Merge agent findings.** Dedup: same file, same dimension, lines within ±5 → keep the more specific / higher-severity finding. Where an agent finding duplicates a confirmed pre-pass hit, keep one (the better-worded).
   - Re-check each surviving finding's severity against the lens — subagents sometimes inflate; the lens severity wins.
   - **Build the coverage ledger v2** — one row per dimension with its source:

     | Dim | Status | Source |
     |---|---|---|
     | §1 Architecture & layering | ✓ 2 findings | S1 agent |
     | §2 Code standards | ✓ clean | S3 agent |
     | §3 Security | ✓ 1 finding | S2 agent + scan |
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

## Review lens

Work through these dimensions in order. If the project has `CLAUDE.md` rules, apply those first — these dimensions extend them.

---

### 1. Architecture & Layering (first-class concern)

The repo enforces a **Controller → Service → Repository → Model** call graph.

**Permitted shortcuts:**
- Controller → Repository is acceptable for **read-only** lookups.
- Controller → Repository for **write** operations is 🟡 Warning — writes must go through a Service to keep transactions and side-effects in one place.

Every violation of the layering rules below is at minimum 🟡 Warning.

When one changed line matches several §1/§4 rules at once (e.g. an inline Eloquent query in a controller trips §1a, §1c, and §4b), post a **single comment anchored to the outermost layering violation**, folding in any distinct remedy (e.g. §4b's eager-load fix) rather than emitting three overlapping findings.

#### 1a. Controller responsibilities

Controllers are HTTP adapters only. They must:
- Receive a typed `FormRequest` (validation already done)
- Call one Service method (or a Repository for simple reads) with plain values or a DTO
- Return an API Resource or a paginated collection Resource

Controllers must NOT:
- Contain **non-trivial branching or calculation that decides a business outcome** — multi-step workflows, business rules, domain math — 🟡 Warning. Do **not** flag guard clauses / route-state checks (`if (! $order) abort(404)`), null/existence checks, presentational branching (`$class = $active ? 'on' : 'off'`), or defaulting a request param (`$page = $request->page ?? 1`).
- Issue Eloquent queries or call Model static methods directly — 🟡 Warning
- Call a Repository **write** method (`create` / `update` / `delete` / `save` / `upsert` / attach-detach) directly — 🟡 Warning. The "or a Repository for simple reads" allowance above is **read-only**; writes carry business consequences (transactions, events, side-effects) and must go through a Service. Judge write-vs-read by whether the method **mutates state**, not by substring — `getUpdatedSince()`, `findDeleted()`, `listCreatedBetween()` are reads. Don't flag controller→Repository *read* calls — they're the sanctioned pattern.
- Call `$request->validate(...)` inline — use a `FormRequest` — 🟡 Warning
- Contain manual authorization (e.g. `if ($user->role === ...)`) — use Policies/Gates; see §3a (canonical) — 🟡 Warning
- Return `$model->toArray()`, `response()->json($model)`, or a raw array instead of an API Resource; see §4a (canonical) — 🟡 Warning
- Have a constructor injecting more than 5 dependencies — 🔵 Suggestion (God controller smell)

```php
// BAD — everything wrong at once
class UserController extends Controller {
    public function store(Request $request) {
        $request->validate(['name' => 'required']);
        $user = User::create($request->all());
        return response()->json($user->toArray());
    }
}

// GOOD
class UserController extends Controller {
    public function store(StoreUserRequest $request, UserService $service): UserResource {
        $user = $service->create(UserData::fromRequest($request));
        return new UserResource($user);
    }
}
```

Controller method length: flag at **40+ lines** as 🔵 Suggestion (suggest extracting to Service).

#### 1b. Service responsibilities

Services own all business logic. They must:
- Accept plain values or typed DTOs — never a `Request` object — 🟡 Warning
- Delegate all Eloquent/query work to a Repository — 🟡 Warning
- Be HTTP-agnostic: no `auth()`, `request()`, `Auth::`, `redirect()`, `response()`, `session()` — 🟡 Warning (canonical list of HTTP helpers banned in Services)
- Be injectable via the service container — `new ServiceClass()` inside another Service — see §4f (canonical)

Service method length: flag at **30+ lines** as 🔵 Suggestion.

#### 1c. Repository responsibilities

Repositories own all Eloquent/query logic. They must:
- Return typed objects (`Model`, `Collection`, `?Model`) — returning a plain `array` is 🔵 Suggestion
- Contain no business logic, no HTTP concerns — 🟡 Warning
- Use Eloquent scopes for reusable filter chains — a very long query chain where a named scope would help readability is 🔵 Suggestion
- Avoid eager-loading constraints inside relationship methods — those belong in the Repository query, not on the Model; see §5 (canonical)

**Repository granularity — one per aggregate root, not one per Model.** A Repository owns an entire domain aggregate. Models that exist only as children of another aggregate root (data / details / items / attachments / metadata rows with a FK to a parent and no independent lifecycle outside it) belong inside the parent's Repository — do **not** create a separate Repository for them.

- Adding a new `XYRepository` when `XRepository` already exists, and `XY` is a child of `X` (FK to `X`, no standalone use) — 🔵 Suggestion. The queries belong in `XRepository`; this is a structural refactor, not a runtime bug.
- A Service or Controller querying a child Model directly (via the Model facade or bypassing the parent Repository entirely) when the parent Repository exists — 🟡 Warning. This is a real layering violation — add the method to the parent Repository instead.
- Naming-heuristic guidance for the reviewer: if a new Repository's name shares a prefix with an existing one (e.g. `Appraisal`/`AppraisalData`, `Order`/`OrderItem`), consider folding it — `AppraisalData` queries belong in `AppraisalRepository`, not a new `AppraisalDataRepository`. Apply judgement: many shared-prefix pairs are genuinely independent (`Product`/`ProductCategory`, `Payment`/`PaymentMethod`, `User`/`UserGroup`).

**Exceptions** — a "child" Model gets its own Repository when it is genuinely its own aggregate: it has an independent lifecycle, is referenced from multiple unrelated aggregates, or belongs to its own bounded context (`User`, `Address`, `Tag`, `Currency`).

#### 1d. DTOs for cross-layer data

Data passing **into** or **out of** a Service must use a typed DTO class, not a raw `array`. Flag any Service method signature that accepts `array $data` as 🔵 Suggestion.

```php
// BAD — raw array crossing layer boundary
$service->create(['name' => $request->name, 'email' => $request->email]);

// GOOD — typed DTO
final class UserData {
    public function __construct(
        public readonly string $name,
        public readonly string $email,
    ) {}

    public static function fromRequest(StoreUserRequest $request): self {
        return new self(name: $request->name, email: $request->email);
    }
}
```

DTOs live under `app/Data/`. They must be pure value containers — no DB writes, HTTP calls, or event dispatching inside them.

#### 1e. Form Request classes for all validation

Every Controller method that accepts user input must type-hint a dedicated `FormRequest` subclass. Inline `$request->validate([...])` in a Controller or Service is 🟡 Warning (this is the canonical rule for inline validation — the Controller case is also listed in §1a's checklist). A `FormRequest` with an empty `rules()` method is also 🟡 Warning.

Use a `Rule` object where a string rule can't express the constraint — `Rule::unique()->ignore()` / `->where()`, or a dynamic `Rule::in([...])` — 🔵 Suggestion. Plain string rules (`required|email`, unqualified `unique:`/`exists:`) are the default and are **not** flaggable.

#### 1f. Console Commands

`handle()` in a Console Command is a thin CLI adapter — it must delegate to a Service or Repository. Direct Eloquent queries or business logic inside `handle()` is 🟡 Warning. Use `$this->info()` / `$this->error()` for output (not `echo`) — 🔵 Suggestion.

#### 1g. Object-oriented structure — interfaces, abstract & final classes, inheritance

Suggest OOP structure **only when the code shows a concrete need** — all 🔵 Suggestion. This dimension is where reviewers most often over-engineer; the default is *no change*, and a working concrete class with one implementation is not a finding. **Do not** suggest an abstraction for a single, stable implementation. YAGNI wins.

**Judge the change against existing code, not in isolation.** This dimension is an explicit exception to the diff-only scope rule: to apply it you **may and should read related existing code** the change integrates with — sibling classes that fill the same role, an existing interface/contract, an abstract base or the class being extended, an existing Repository/Service with the same prefix (see §1c). A new class only reveals a duplication or a missing-contract smell when you compare it to what's already there. **But anchor every finding to the changed code** — e.g. "this **new** `StripeGateway` duplicates the existing `PaypalGateway`; extract a shared `PaymentGateway` contract" — never flag a pre-existing issue inside an untouched file. Read the old code to judge the new; report on the new.

**Extract an interface (contract) — only with a real reason.** Flag when:
- **Two or more** classes already fill the same conceptual role with the same shape and share **no** interface → propose a contract they both implement.
- A **swappable / pluggable collaborator** is type-hinted as a concrete class where a contract would decouple it and make it fakeable in tests — a payment gateway, notification channel, external API client, or a Strategy picked at runtime.

  ```php
  // Worth a contract — multiple interchangeable implementations
  interface PaymentGateway { public function charge(Money $amount): Receipt; }
  final class StripeGateway implements PaymentGateway { ... }
  final class PaypalGateway implements PaymentGateway { ... }
  ```

  **Do NOT flag** a Service/Repository with **one** implementation and no polymorphism or test-double need just for "missing an interface" — an interface-per-class with a single impl is cargo-cult; Laravel binds concretes fine. No speculative "might have another impl someday."

**Reuse before rebuild; extract when a responsibility is inline** (judgement):
- The change adds logic an **existing** class / Service / Action / helper already provides → reuse it instead of duplicating (🔵; 🟡 when it duplicates non-trivial existing behaviour — a real DRY/maintenance risk). This uses the same read-existing-code allowance above; anchor the finding to the new code ("this new block re-implements `App\Support\PriceCalculator`").
- The change crams a **distinct responsibility** inline — a chunk of business logic inside a controller/model/command, a substantial repeated block with its own reason to change → suggest extracting a dedicated class (Service, Action, DTO, value object, Job) — 🔵.
- Don't invert it into noise: no new class when an existing one is the right home, and no extraction of a trivial one-liner.

**Abstract base class vs trait vs composition.** When sibling classes share real duplicated behaviour:
- A genuine **is-a** family with shared state + template steps → an `abstract` base class (and mark it `abstract` if it's only meaningful as a parent yet is currently instantiable).
- Cross-cutting reuse with **no** is-a relationship → a **trait** or a collaborator, **not** inheritance.
- **Prefer composition over inheritance.** Flag `extends` used purely to share code (no true is-a). Flag inheritance depth **≥3 levels only when the change itself adds the `extends`** that lands the chain there — phrase it against the new subclass; don't flag a deep chain the diff merely touches.

**`final` for new leaf classes.** A new class not designed for extension (no `protected` extension points, not abstract, not a framework base you must subclass) *may* be `final`. Flag a missing `final` **only when sibling leaf classes in the same diff or directory are already `final`** — i.e. the codebase demonstrably uses it as a convention. Never mass-suggest `final` on a codebase that doesn't. 🔵.

**Program to the abstraction.** Once a contract exists, inject and type-hint the **interface**, not the concrete class.

---

### 2. PSR-12 & Code Standards

#### 2a. `declare(strict_types=1)` — enforce when applicable

All new PHP files under `app/` must open with `declare(strict_types=1)` as the first statement after `<?php`. Flag as 🔵 Suggestion. The `app/` scope is deliberate — migrations, config, and route files are out of scope.

**Edited legacy files count too.** When the diff meaningfully changes the logic of an existing `app/` file that lacks the declaration, flag it (🔵) — the convention is *add when touching*, so a touched file is an applicable file. Apply judgment on "applicable":

- **Do flag:** new files; edited files where the diff adds/changes methods or logic.
- **Don't flag:** a trivial touch to a legacy file (one-line unrelated fix, rename ripple, formatting) — demanding a semantics-affecting declaration on a file the PR barely touches is scope creep.
- **Phrase with the risk in view:** adding `strict_types` changes coercion semantics for the *whole file*, not just the diff'd lines — a latent loose-type call elsewhere in the file can start throwing. Suggest it alongside a check that the file's tests cover the untouched paths (or a quick scan of the file's other call sites), not as a blind one-liner.

```php
<?php

declare(strict_types=1);

namespace App\Http\Controllers;
```

#### 2b. Type declarations — MUST FIX (🟡 Warning)

**Every method signature must declare types for every parameter AND a return type.** This applies to public, protected, and private methods on classes, traits, and abstract classes alike. Both missing parameter types and missing return types are 🟡 Warning.

- `void` — no return value
- `never` — always throws or exits
- `self` / `static` — fluent setters
- `?Type` — nullable; use instead of untyped nullable
- `mixed` — acceptable as a deliberate choice, not a placeholder
- Eloquent relation types: `BelongsTo`, `HasMany`, `MorphMany`, etc. on Model relationship methods

**Exemptions:**
- `__construct` / `__destruct` cannot declare a return type — don't flag one as missing.
- Closures passed to Pest's `it()`, `test()`, `describe()`, `beforeEach()` do not need return types.
- Magic methods (`__get`, `__set`, `__call`) follow PHP's required signature.

#### 2c. Property type declarations

Class properties under `app/` must be typed. 🔵 Suggestion.

**Exempt** (Eloquent framework-magic arrays): `$fillable`, `$casts`, `$guarded`, `$with`, `$appends`, `$hidden`, `$dates`.

```php
// BAD
class UserService {
    private $users;
}

// GOOD
class UserService {
    private UserRepository $users;
}
```

#### 2d. Naming conventions

| Element | Convention | Example |
|---|---|---|
| Classes | `PascalCase` | `UserRepository` |
| Methods & variables | `camelCase` | `getActiveUsers()` |
| Constants / enum cases | `SCREAMING_SNAKE_CASE` | `MAX_RETRIES` |
| Database columns | `snake_case` | `created_at`, `user_id` |
| Blade views | `kebab-case.blade.php` | `user-profile.blade.php` |
| Route URIs | `kebab-case` | `/user-profiles/{id}/payment-methods` |
| Model names | Singular | `User`, `Order` |

#### 2e. Positive conditionals (if/else only)

When an `if` has an `else` branch, the `if` should test the **positive/truthy** case, not a negation — the reader shouldn't have to mentally invert the condition and then read the `else` as "the normal case". Flag `if (<negated>) { … } else { … }` as 🔵 Suggestion: swap the branches and drop the negation.

```php
// BAD — negated if with an else (neither branch exits)
if (! $user->isActive()) {
    $badge = 'inactive';
} else {
    $badge = 'active';
}

// GOOD — positive if, branches swapped
if ($user->isActive()) {
    $badge = 'active';
} else {
    $badge = 'inactive';
}
```

**Precedence:** this rule is for an if/else where **neither branch exits**. When the `if` branch already exits (`return`/`throw`/`continue`/`break`), don't swap-and-keep the `else` — prefer §2f (drop the `else` altogether); raise §2f, not §2e, and emit one combined finding. (§2g's deep-nesting rule only applies at ≥3 levels, so it doesn't compete here.)

**Strictly scoped — do NOT flag:**
- **Guard clauses / early returns with no `else`** — `if (! $user) { return; }`, `if (! $ok) { abort(404); }`. These are the *preferred* idiom (they avoid nesting); a negation here is correct and good. The rule applies **only** when a real `else` (or `elseif`) branch exists.
- **Compound conditions** — for `if (! $a && ! $b)`, do **not** mechanically apply De Morgan (→ `if ($a || $b)` with swapped branches). That's a correctness risk; flag-only at most, never auto-rewrite.
- Conditions where the negative is genuinely the natural primary case and flipping reads worse — use judgement; this is a Suggestion, not a mandate.

When auto-fixing, only swap branches + remove the leading `!` on a simple condition. Leave compound/De-Morgan cases for the developer.

#### 2f. Redundant else after return

When the `if` branch ends in `return` / `throw` / `continue` / `break`, the `else` is dead weight — drop it and de-indent the trailing block. 🔵 Suggestion.

```php
// BAD
if ($user->isActive()) {
    return $this->grant();
} else {
    return $this->reject();
}

// GOOD
if ($user->isActive()) {
    return $this->grant();
}

return $this->reject();
```

#### 2g. Guard clauses over deep nesting

Code nested **≥3 levels** of `if` where an early `return` / `continue` / `throw` would flatten it ("arrow code") — 🔵 Suggestion. Invert the outer conditions into guard clauses so the happy path reads top-to-bottom at the base indent. Only flag genuine nesting; a single `if` body is fine.

```php
// BAD — arrow code
public function handle($order): void {
    if ($order) {
        if ($order->isPaid()) {
            if (! $order->isShipped()) {
                $this->ship($order);
            }
        }
    }
}

// GOOD — guard clauses
public function handle($order): void {
    if (! $order) return;
    if (! $order->isPaid()) return;
    if ($order->isShipped()) return;

    $this->ship($order);
}
```

#### 2h. Nested ternaries

A ternary nested inside another (`$a ? $b : ($c ? $d : $e)`) — 🔵 Suggestion. Rewrite as a `match (true)`, an if/elseif chain, or extract a method. (PHP 8 already errors on *un-parenthesised* nesting — this targets the parenthesised-but-unreadable form.) A single, flat ternary is fine — don't flag those.

#### 2i. Magic numbers and strings

Unexplained literals that encode meaning — HTTP status codes (`200`, `422`), role/status strings (`'admin'`, `'pending'`), business limits (`if ($attempts > 5)`) — should be a named constant, enum case, or config value. 🔵 Suggestion.

- **Exempt:** `0`, `1`, `-1`, array indices, obvious unit math (`* 60`, `/ 100`), and test data.
- Status/role strings are the highest-value target — they usually map to an existing enum.

```php
// BAD
return response()->json($data, 422);
if ($user->role === 'admin') { ... }

// GOOD
return response()->json($data, Response::HTTP_UNPROCESSABLE_ENTITY);
if ($user->role === Role::Admin) { ... }
```

#### 2j. Boolean flag arguments

A boolean literal passed at a call site (`$service->generate($data, true, false)`) is unreadable — the reader can't tell what `true` means without opening the signature. 🔵 Suggestion. Prefer two intention-revealing methods, a named enum, or (last resort) a named argument (`generate($data, force: true)`). Judgement rule — a single, obvious boolean on a well-named method is acceptable. When the call is into a **framework/vendor method the author can't change** (`->paginate(15, ['*'], 'page', false)`), suggest only a **named argument** — not splitting or an enum.

#### 2k. Long parameter lists

A method/constructor with **more than 5** parameters — 🔵 Suggestion. Group related params into a DTO (see §1d) or a value object. A controller constructor whose parameters are injected dependencies is judged under §1a's DI cap, **not** here — don't also raise §2k for it.

#### 2l. Double negatives

A negatively-named variable then tested negatively — `$notReady` with `if (! $notReady)`, `$isInvalid` with `! $isInvalid` — forces a double mental inversion. 🔵 Suggestion. Rename to the positive (`$ready`, `$isValid`) and flip the uses.

#### 2m. `count()` for emptiness checks

`count($x) > 0` / `count($x) === 0` to test emptiness — 🔵 Suggestion. Use `! empty($x)` / `empty($x)` for arrays, or `$collection->isNotEmpty()` / `->isEmpty()` for Eloquent collections — clearer intent and (for collections) avoids materialising a count.

#### 2n. Descriptive, meaningful names — 🔵 Suggestion

§2d governs *casing*; this rule governs whether the name actually says what the thing is. A name that is correctly `camelCase` but opaque (`$tmp`, `$d`) is worth a nudge. It's 🔵 — an opaque-but-honest name is a readability suggestion; a name that actively *misleads* about behaviour is the 🟡 case in §2p. Flag identifiers — variables, properties, parameters — whose name does not convey their role (**method** names are governed by §2p):

- **Cryptic / single-letter variables** outside the idioms below — `$d`, `$x`, `$a2`, `$str`, `$obj`.
- **Vague placeholder names** that carry no meaning — `$data`, `$data2`, `$tmp`, `$temp`, `$val`, `$arr`, `$res`, `$info`, `$thing`, `$stuff`, `$foo`. (`$result` is fine when it genuinely *is* the result of the method.) **Judge by role, not spelling:** a short-lived local whose meaning is obvious from the adjacent line — e.g. `$data` passed straight into `Model::create($data)` — is acceptable; don't flag a name the surrounding context already explains.
- **Unclear abbreviations** that aren't well-known — `$usrRepo` → `$userRepository`, `$calcAmt` → `$calculatedAmount`, `$ctr` → `$counter`.
- **Vague dependency names — however the dependency arrives.** Applies to any variable or property holding a dependency or collaborator: constructor promotion, method/closure injection, container resolution (`app()`, `resolve()`, `App::make()`), or direct instantiation (`new Foo()`). The test is **"does the name say what this dependency does / holds?"** — not whether it's short, and not whether it echoes the type. A name that says nothing about the role (`$helper`, `$manager`, `$service`, `$obj`, or a type fragment that drops the meaning, e.g. `$sample` for a `*SampleData` class) — 🔵; suggest a role-carrying name. Class properties get the strictest read: they're used (`$this->sample`) far from their typed declaration, so the adjacent-context carve-out for locals does **not** apply there — the name alone must carry the role. Don't demand a verbatim class-name echo (it adds length, not clarity) — a shortened form that still names the role is the target. Don't flag a name that already **is** the role, including conventional dependency names: `$logger`, `$mailer`, `$cache`, `$clock`, `$config`, `$client` (for an SDK/HTTP client), `$connection`, `$validator`, `$userRepository` and other `*Repository` / `*Service` camelCase-of-type forms.
- (Vague/opaque **method** names — `process()`, `doStuff()`, `getData()`, `run2()` — are covered in §2p, not here.)

```php
// BAD — opaque variables (method name is a §2p concern, left unchanged here)
public function applyGstToLineTotals(array $d): array {
    $tmp = [];
    foreach ($d as $x) {
        $tmp[] = $x->total * 1.1;
    }
    return $tmp;
}

// GOOD — names convey role
public function applyGstToLineTotals(array $lineItems): array {
    $totalsWithGst = [];
    foreach ($lineItems as $lineItem) {
        $totalsWithGst[] = $lineItem->total * 1.1;
    }
    return $totalsWithGst;
}
```

**Exemptions — do NOT flag:**
- **Conventional short names:** `$i` / `$j` / `$k` as classic `for` counters, `$e` for the exception in a `catch`, `$q` / `$query` for a query builder in a scope closure, `$key` / `$value` in array iteration, `$id`.
- **Well-known acronyms / domain terms:** `$url`, `$id`, `$db`, `$dto`, `$http`, `$api`, `$pdf`, `$csv`, `$ui`, `$io`.
- **Framework-required method names:** `handle()` on Jobs / Commands / Listeners / Middleware, `__invoke()`, `boot()`, `register()`, `up()` / `down()` in migrations, `rules()` / `authorize()` on FormRequests, `toArray()` on Resources, Eloquent relationship method names.
- A short closure parameter whose meaning is obvious from one line of surrounding context — use judgement; the bar is "would a new reader know what this holds?"

#### 2o. Comments — only where the code can't explain itself — 🔵 Suggestion

Default to **no comment**: clear names, small methods, and early returns should carry the meaning on their own. A comment earns its place only by explaining a non-obvious **why** — a constraint, a workaround, a business/regulatory reason the code itself cannot show — never by restating **what** the code already says. The first fix for unclear code is a clearer name or an extracted method, not a comment that narrates it. Flag three things:

- **Redundant / narrating comments** that restate what the code already says — whether line-level (`$i++; // increment i`, `// return the result`) or a **step-label / section-divider** announcing a self-evident block (`// Loop through the orders`, `// Validate the request`, `// Build the payload`, `// Save to the database`, `// Set the properties`). If the comment just translates the next line(s) into English, delete it — the code already reads that way, and the comment only adds noise and drifts out of date. When a block genuinely needs a label to be followable, that's the signal to **extract it into a well-named method**, not to caption it.
- **Commented-out code this change added** — delete it. Git history preserves anything you might want back; dead code in the file is just clutter. (Only flag commented-out code on the diff's added lines — don't flag pre-existing commented code sitting on a context line.)
- **A genuinely hard-to-follow block with no explanatory comment** — when logic is unavoidably dense (a tricky algorithm, a non-obvious edge-case guard, a deliberate deviation from the obvious approach), a short *why* comment is warranted. Suggest adding one, or refactoring so it isn't needed.

```php
// BAD — restates the code
// increment the counter by one
$counter++;

// BAD — step-label narrating a self-evident block; the code already says this
// Build the order payload
$payload = [
    'customer_id' => $customer->id,
    'total'       => $total,
];
// Save the order
$order = Order::create($payload);

// BAD — dead code left behind
// $user->notify(new OldWelcome($user));
$user->notify(new Welcome($user));

// GOOD — explains a non-obvious *why*
// Stripe rounds half-up; we floor here to match the ledger's banker's rounding.
$amount = (int) floor($cents);
```

**Exemptions — do NOT flag:**
- **PHPDoc that adds information the signature can't express** — generics / array shapes (`@param array<int, User>`, `@return Collection<int, Order>`), `@throws`, `@deprecated`, `@see`.
- **Tooling pragmas** — `// @phpstan-ignore-line`, `// phpcs:ignore`, `// @noinspection`, Pint/Psalm directives.
- **Intentional markers** — `// TODO`, `// FIXME`, `// HACK`. These are signals, not noise.
- **Licence / file headers.**

#### 2p. Method names — verb phrases (🔵) and name-matches-behaviour (🟡)

A method *does* something, so its name should start with a verb: `calculateTotal()`, `sendInvoice()`, `markAsPaid()`, `syncTags()` — not a bare noun like `total()`, `invoiceData()`, or `tags()` (for a method that performs work). Flag a method whose name is a noun/adjective with no verb as 🔵 Suggestion, suggesting a verb-led rename. A **vague/opaque action name** that has a verb but says nothing — `process()`, `doStuff()`, `handle2()`, `getData()`, `manage()` — is worse: 🟡 Warning; name the action and its subject (`calculateInvoiceTotal()`, `markOrderShipped()`).

```php
// BAD — noun names for methods that do work
public function totals(Order $order): Money { /* computes */ }
public function invoicePdf(Order $order): string { /* generates */ }

// GOOD
public function calculateTotals(Order $order): Money { ... }
public function generateInvoicePdf(Order $order): string { ... }
```

**Explicitly exempt — these are *conventionally* nouns/adjectives; do NOT flag:**
- **Eloquent relationships** — `user()`, `orders()`, `latestInvoice()`. Nouns by Laravel convention.
- **Accessors / attributes** — `fullName(): Attribute`, `getFullNameAttribute()`.
- **Boolean predicates** — `is*` / `has*` / `can*` / `should*` / `was*` (`isActive()`, `hasPermission()`). These already read as verbs.
- **Query scopes** — `scopeActive()` (the `scope` prefix is the convention; the suffix is an adjective by design).
- **Framework-required names** — `handle()`, `boot()`, `register()`, `rules()`, `authorize()`, `up()` / `down()`, lifecycle hooks.
- **Fluent/builder returns and enum/value-object helpers** where a noun reads naturally (`->name()`, `Money::zero()`).

The rule targets *action* methods named as nouns. When in doubt — if the method has side effects or computes something — it wants a verb; if it's a typed property-like accessor or a relationship, leave it.

**Name must match behaviour — 🟡 Warning.** Beyond being a verb, the name must accurately describe what the method *actually does*. A name that misleads is worse than a vague one — it lies to every caller. Flag when the verb contradicts or hides the behaviour:

- A read-implying verb (`get`, `find`, `fetch`, `load`, `calculate`, `format`, `build`) on a method that **mutates state, persists, deletes, or dispatches events/jobs/mail** — the side effect is invisible at the call site. Rename to reflect it (`getOrCreateUser()`, `calculateAndStoreTotals()`, or split the method).
- A verb that names the **wrong action** — `updateUser()` that actually creates, `validateInput()` that also saves, `deleteX()` that soft-disables.
- A name describing **less than the method does** — `sendEmail()` that also updates the record and logs an audit entry; the extra responsibilities are hidden (often also a single-responsibility smell — see §1b).

```php
// BAD — name says "get" (pure read) but it writes
public function getActiveSubscription(User $user): Subscription {
    return $user->subscription ?? $user->subscriptions()->create([...]); // creates!
}

// GOOD — the name tells the truth
public function getOrCreateActiveSubscription(User $user): Subscription { ... }
```

Use judgement and read the body before flagging — this requires understanding what the method does, not just its signature. A correctly-named method with an obvious, expected side effect (e.g. `save()`, `dispatch()`) is fine.

---

### 3. Security

#### 3a. Authorization — Policies and Gates

Authorization for a model action should go through a **Policy or Gate** — `$this->authorize('update', $model)`, `authorizeResource()`, `Gate::authorize()`, `@can`, or `->can:` route middleware — not inline conditionals. Manual role/permission checks in Controllers or Services are 🟡 Warning:

```php
// BAD
if (auth()->user()->role === 'admin') { ... }
if ($request->user()->is_admin) { ... }

// GOOD
$this->authorize('update', $user);
Gate::authorize('update-user', $user);
```

**A Policy exists for the model but the action doesn't call it** — if `app/Policies/{Model}Policy.php` defines the relevant ability and a controller action on that model performs no `authorize` / Gate / `can` check, flag 🟡 Warning, confirm-not-accuse: "a `{Model}Policy` exists — wire it up (`$this->authorize(...)`) or confirm authz is applied via route middleware." **If applicable** only: don't demand a Policy for genuinely public/global or read-only lookups, trivial reference data, or where a route-level `can:` already covers the action.

A `FormRequest::authorize()` that unconditionally returns `true` without a comment explaining why is 🔵 Suggestion — but only for a request that plausibly needs authorization (mutating an owned resource, an admin action). Don't flag it on a genuinely public, read-only endpoint. A short comment (`// public endpoint`) is a valid escape hatch.

**Missing auth guard on a newly-added route.** When the diff **adds** a mutating route (`POST` / `PUT` / `PATCH` / `DELETE`) that is not inside an authenticated/authorized route group and carries no `->middleware(...)` / `->can(...)`, flag it 🟡 — confirm-not-accuse: "confirm authz is applied (route group, controller `__construct`, or a Policy) or this endpoint is intentionally public." Only fire on a **route registration** the diff adds; do **not** flag a bare controller-method addition (its guard usually lives in the route group or constructor you may not see).

#### 3b. Mass assignment

🟡 Warning:

```php
// BAD
User::create($request->all());
$user->update($request->all());
$user->fill($request->all())->save();

// GOOD
$user->update($request->safe()->only(['name', 'email', 'phone']));
```

`$guarded = []` without an explicit `$fillable` list — see §4d (canonical rule).

#### 3c. SQL injection in raw queries

🔴 Critical — **a variable interpolated into any raw-SQL sink**: `whereRaw` / `orderByRaw` / `havingRaw` / `groupByRaw` / `selectRaw`, `DB::raw()`, `DB::statement()`, and `DB::select/update/delete($sql)`. The trigger is string **interpolation**; a static string or an already-parameterised call does not fire.

```php
// BAD — value injected
->whereRaw("name = '$name'")
DB::statement("DELETE FROM users WHERE id = $id")
// BAD — column/direction injected (bindings can't fix this one)
->orderByRaw("$column $direction")

// GOOD — bind values with ?
->whereRaw('name = ?', [$name])
```

Values bind with `?` placeholders. **Identifiers (column/table/direction) cannot be bound** — validate them against an allow-list before interpolating; never pass a request value straight into `orderByRaw`.

#### 3d. Insecure direct object reference (IDOR)

A resource fetched by a **request-supplied ID** without scoping to the authenticated user is IDOR. Severity by what happens to the fetched model:

- The model is then **mutated, deleted, or its ownership-bound data written** — 🔴 Critical (a request-supplied ID that lets a user alter another user's record is a data-breach/tamper path).
- The model is only **read/returned** — 🟡 Warning.

```php
// BAD — request id, no ownership scope; if this then ->update()/->delete() it's 🔴
$order = Order::findOrFail($request->order_id);
$order->update($request->validated());

// GOOD — scoped to the owner
$order = auth()->user()->orders()->findOrFail($request->order_id);
```

**Check for guards you may not see before flagging.** The ownership/authz check can live outside the fetch line: inspect the same method and its `FormRequest::authorize()` for a user-scoped query, a Policy, `$this->authorize()`, `Gate::authorize()`, or `authorizeResource()`; and route middleware (`can:`) may not be in the diff at all. If a guard is plausibly present but you can't see it, **phrase the finding as a question** ("confirm ownership is enforced on `$request->order_id`") rather than an assertion. Do **not** flag genuinely global / reference resources (a public `Product`, a lookup table) that aren't user-scoped by design.

#### 3e. File upload security

🟡 Warning — a FormRequest that accepts file uploads without **both** a type allow-list and a size cap. Either `mimes:` or `mimetypes:` is acceptable (both sniff actual file contents):

```php
// BAD
'photo' => 'required|file'

// GOOD — string rules
'photo' => 'required|image|mimes:jpeg,png,webp|max:5120'
'photo' => 'required|image|mimetypes:image/jpeg,image/png|max:5120'

// GOOD — fluent File rule objects satisfy both controls despite no mimes:/max: tokens
'photo' => ['required', File::image()->max(5 * 1024)],
'doc'   => ['required', File::types(['pdf','docx'])->max(10 * 1024)],
```

Don't assume the controls are absent when the rules come from a shared/base FormRequest or a custom `Rule` object you can't see — confirm rather than assert. Note: bare `image` alone is **not** a sufficient type allow-list (it permits SVG, an XSS vector) — require `mimes:`/`mimetypes:` or `File::types()`.

#### 3f. Sensitive data leaks

- `{!! $var !!}` in Blade or `v-html` in Vue where value could be user-supplied — 🔴 Critical (also §12, §15c). Carve-out: raw echoes of clearly trusted, constant, or server-generated HTML (`{!! Form::open() !!}`, known-sanitizer output, config-constant markup) are not findings. When the value's provenance is unclear, still flag 🔴 but confirm-not-accuse ("confirm `$var` is sanitized/trusted HTML").
- API Resources / responses that surface **credential or session fields** — `password`, `remember_token`, `api_token`, hashed secrets — 🔴 Critical (canonical for credential exposure; §14 covers benign over-exposure). Raw pivot data or other internal columns — 🟡 Warning. Only flag fields actually surfaced in the output, not ones behind a `when()` / `whenLoaded` guard.
- `Log::info()` / `Log::error()` that logs a full request body, password, or token — 🟡 Warning.
- A caught exception's raw detail returned to the client — `$e->getMessage()`, `$e->getTraceAsString()`, `$e->getFile()` / `getLine()`, or the exception object itself — placed in an HTTP / JSON **response** body (`response()->json(['error' => $e->getMessage()])`, `abort(500, $e->getMessage())`, returned or flashed to the user) — 🟡 Warning. Leaks DB errors, file paths, and class/stack internals to the caller. Return a generic client-facing message and send the detail to the log instead (`report($e)` / `Log::error($e)`). Exempt: a `ValidationException` (its 422 message is user-facing by design), and a custom / domain exception carrying a deliberately safe, user-facing message. **The trigger is the message reaching the response — logging it (`report()` / `Log`) is correct and not a finding.** (The success-status half of this is §10.)

#### 3g. `env()` outside config files

🟡 Warning — returns `null` when config is cached in production:

```php
// BAD
$key = env('STRIPE_SECRET');

// GOOD
$key = config('services.stripe.secret');
```

#### 3h. Global forbidden patterns (🟡 Warning in all files)

- `dd()`, `dump()`, `die()` — forbidden in committed code.
- `error_log()`, `var_dump()`, `print_r()`, `echo` used for logging — use `Log::info()` / `Log::error()` / `Log::debug()`. Exempt `print_r($x, true)` / `var_export($x, true)` whose string result is passed into a real `Log::*()` call. (`echo` in a Console Command is §1f, not this.)
- `$_SERVER`, `$_ENV`, `$_GET`, `$_POST`, `$_REQUEST` — use Laravel helpers (`request()`, `config()`).

#### 3i. Hardcoded secrets and credentials — 🔴 Critical

A real secret literal committed to the repo is a security leak, not a style issue. Flag any hardcoded API key, password, token, OAuth/client secret, private key, signing/encryption key, or a connection/DSN string with an embedded password — 🔴 Critical. Move it to `.env` and read it through `config()` (never `env()` outside config — see §3g).

Signals to catch:
- Assignment of a literal that looks like a secret to a variable/property/array key named `*key*`, `*secret*`, `*token*`, `*password*`, `*passwd*`, `*apikey*`, `*auth*`.
- Known credential shapes regardless of the variable name: `sk_live_…` / `sk_test_…` (Stripe), `AKIA…` (AWS), `ghp_…` / `gho_…` (GitHub), `xox[baprs]-…` (Slack), `AIza…` (Google), `-----BEGIN … PRIVATE KEY-----`, Basic-auth in a URL (`https://user:pass@host`). A long base64/hex blob counts **only when it is used as an API key, token, or signing/encryption secret** — not when it's a hash, checksum, or opaque identifier.
- A non-empty password/secret passed directly to a client (`new Client(['secret' => 'abc123…'])`, `Http::withToken('eyJ…')`).

```php
// BAD — secret committed to the repo
$stripe = new StripeClient('sk_live_51H8xY2eZvKf...');
'password' => 'Pr0dDbP@ss!',

// GOOD — from config, value lives in .env (gitignored)
$stripe = new StripeClient(config('services.stripe.secret'));
'password' => config('database.connections.mysql.password'),
```

**When you flag a real (non-placeholder) secret, say so explicitly:** the value must be **rotated/revoked**, not just deleted — it remains exposed in git history. Note that in the finding.

This applies equally to secrets committed in **front-end/JS/Vue or config assets** — a real secret shipped in the browser bundle is *worse* (publicly served), so don't soften it for being client-side. But do **not** flag intentionally-public values: framework-exposed env (`VITE_*`, `NEXT_PUBLIC_*`), publishable keys, or public JWKS. A bare JWT (`eyJ…`) is a finding only when it's a long-lived or signing token, not a short-lived example.

**Exempt — do NOT flag:**
- Obvious dummy/test values in tests, factories, and seeders (`'password'`, `bcrypt('password')`, `'secret'`, `'test-token'`).
- Placeholders and examples (`.env.example`, `'your-api-key-here'`, `'xxxxx'`).
- **Public** keys / publishable keys (`pk_live_…`, public certificates) — not secret by design.
- Non-secret config defaults (timeouts, URLs without credentials).
- **High-entropy values that aren't credentials** — SHA/MD5 hashes, checksums, idempotency or cache keys, migration/UUID literals, encoded data payloads — even when the variable name matches `*key*` / `*token*` / `*auth*`. A matching name alone is not enough; flag only when the value is actually used to authenticate or sign.

---

### 4. Laravel Best Practices

#### 4a. API Resources — no raw `toArray()` or model-to-JSON

A JSON response that returns an **Eloquent model or collection** must use a dedicated API Resource. Raw `->toArray()`, `response()->json($model)`, or `$model->toJson()` in a Controller are 🟡 Warning. This does **not** apply to non-entity payloads — a status/ack (`{status: 'ok'}`), a health check, a webhook 200, or a plain computed array — those need no Resource.

```php
// BAD
return response()->json($user->toArray());

// GOOD
return new UserResource($user);
return UserResource::collection($users);
```

Inside an API Resource's `toArray()`: no DB queries, no Service calls — 🟡 Warning (Resources transform already-loaded data only). Use `$this->whenLoaded('relation')` for a related model **that may not be eager-loaded** — accessing it directly then triggers a lazy query — 🟡 Warning. If the relation is guaranteed loaded (the controller/`$with` always eager-loads it) `whenLoaded` isn't required; when you can't tell the load-state from the change, treat a bare relation access as 🔵, not 🟡.

**No business logic in a Resource** — a Resource shapes a response; it doesn't decide business outcomes — 🟡 Warning. Fires on domain calculations or business rules computed inside `toArray()` (or private methods on the Resource): pricing/tax/total math, deriving a status or entitlement from multiple fields, permission/eligibility decisions, workflow-state branching. Move the logic to the Service (pass the computed value in), a model accessor, or a DTO — where it's testable and reusable — and let the Resource output the precomputed result. **Presentation transforms are the Resource's job — don't flag them:** renaming/nesting keys, formatting dates/numbers for display, `when()` / `whenLoaded()` / `mergeWhen()` conditionals, casting, enum `->label()` / `->value`, trivial concatenation (`full_name`), and null-safe fallbacks. The line: *deciding* a value from business rules = logic (flag); *reformatting* an already-decided value = presentation (fine). A **single-field derivation** (`'is_overdue' => $this->due_at->isPast()`, a null-check boolean) sits on the line — treat it as presentation, 🔵 at most. Route the value to the right home: a simple derivation fits a model accessor; **branching business rules (tiered tax, eligibility trees) belong in a Service/DTO, not an accessor** (§5 flags complex logic in models too). If the offending line is *also* a DB query or Service call (previous paragraph), report it **once** — as this rule — not twice.

```php
// BAD — business rule decided in the Resource
public function toArray($request): array {
    return [
        'total' => $this->price * $this->qty * (1 + ($this->resource->isExport() ? 0 : 0.1)),
        'can_renew' => $this->expires_at->isFuture() && $this->payments_count > 0 && ! $this->suspended_at,
    ];
}

// GOOD — Resource outputs precomputed values
public function toArray($request): array {
    return [
        'total' => $this->total_with_gst,        // branching tax rule → computed by Service
        'can_renew' => $this->can_renew,          // eligibility tree → Service / Policy
        'expires_at' => $this->expires_at->toIso8601String(),  // formatting is fine
    ];
}
```

#### 4b. Eloquent N+1 queries

Any Eloquent query or relationship access inside a loop body without prior eager loading is 🟡 Warning. `->load()` inside a loop is the same violation — lift it above the loop.

```php
// BAD — 1 query per user
foreach ($users as $user) { echo $user->profile->bio; }

// BAD — ->load() inside loop, same N+1
foreach ($orders as $order) { $order->load('items'); }

// GOOD
$users = User::with('profile')->get();
// or for load:
$orders->load('items');  // before the loop
```

**Manual cross-table queries via the FK count too.** This rule is **model-agnostic** — apply it to *every* parent / child pair in the codebase, not just ones that look like the examples below. Any code path that fetches an Eloquent model and then re-fetches a related model by its FK with a second `Model::find()` / `Model::where(...)->first()` is an N+1-shaped query — even outside a loop, and it always scales to N+1 once a loop wraps it. Use a defined relationship + `->with()` (or `->load()`) instead — 🟡 Warning.

```php
// BAD — two queries; in a loop this is N+1
foreach ($orders as $order) {
    $customer = Customer::find($order->customer_id);
    // ...
}

// BAD — same shape outside a loop, any parent/child pair (either direction)
$invoice = Invoice::find($id);
$client  = Client::find($invoice->client_id);

// BAD — manually querying children instead of using the relation
$user      = User::find($id);
$addresses = Address::where('user_id', $user->id)->get();

// GOOD — one query with the relation eager-loaded
$orders = Order::with('customer')->get();
foreach ($orders as $order) {
    $customer = $order->customer;
}

// GOOD — single query for the standalone case
$invoice = Invoice::with('client')->findOrFail($id);
$client  = $invoice->client;

// GOOD — use the relation, not Model::where(fk)
$user      = User::with('addresses')->findOrFail($id);
$addresses = $user->addresses;
```

**If the relationship isn't defined on the Model yet, the fix is to define it** (`public function customer(): BelongsTo`, `public function items(): HasMany`, …) — not to keep manually joining via `Model::find($fk)` or `Model::where('fk_column', …)`.

**Report each logical N+1 once**, at its root cause (the missing eager-load), not at every site that consumes the relation.

#### 4c. Eloquent scopes

Repeated query chains belong in a named local scope. Flag duplicated filter chains as 🔵 Suggestion.

#### 4d. Fillable / guarded hygiene

`$guarded = []` without an explicit `$fillable` — 🔵 Suggestion (flag, suggest `$fillable`).

#### 4e. Jobs, Events, Listeners, Observers — when to require them

**Use a Job — 🟡 Warning** when the change does slow work **synchronously in a request path**, anchored to observable signals (not an unmeasurable time threshold): a synchronous `Mail::send()` / `Notification::send()`, inline PDF/image/report generation, or a loop making external HTTP calls. A single inline `Http::` call — flag only when it's fire-and-forget (the response is unused). **Exempt** Mailables/Notifications that implement `ShouldQueue`, and `Mail::queue()` / `->queue()`. "Needs retry" is a soft cue, not a trigger on its own.

**Use an Event + Listener — 🔵 Suggestion** when one action triggers multiple unrelated side effects (altitude improvement, not a defect).

**Use an Observer — 🔵 Suggestion**, and only on a diff-visible signal: the change adds a **second** handler for the same Model lifecycle hook within the changed file. Don't infer "handled in multiple places" from code you can't see.

```php
// BAD — synchronous email blocks the request
Mail::to($user)->send(new WelcomeMail($user));

// GOOD
SendWelcomeMail::dispatch($user);
// or
event(new UserRegistered($user));
```

#### 4f. Dependency Injection

`new ClassName()` inside a Controller, Service, or Repository where the class should be injected is 🔵 Suggestion. This includes `new OtherService()` inside a Service constructor body.

**Injected dependencies should be `private readonly`** — on a **new or substantially rewritten** class, promoted constructor dependencies (Services, Repositories, clients) declared without `readonly` — 🔵 Suggestion. `private readonly UserRepository $userRepository` makes the dependency immutable after construction and documents that nothing swaps it mid-lifecycle. Don't flag legacy classes the diff merely touches, properties that are genuinely reassigned (verify before suggesting), or non-dependency value properties. **Exempt queued Jobs** — a service dependency constructor-injected into a Job is its own smell (the Job is serialized; resolve dependencies in `handle()` instead), so suggest moving the dependency to `handle()`, not adding `readonly`.

#### 4g. `DB::transaction()` for multi-write paths (canonical)

Two or more writes that **must commit or roll back together** — a parent plus its children, a debit plus its credit — belong in `DB::transaction()`. A missing transaction on such a path is 🟡 Warning: if the second write fails, the first stays committed and related rows are left inconsistent. A single Eloquent call that happens to issue several statements (e.g. `create()` with a `creating` hook) is **one logical write** — don't flag it; and genuinely independent writes with no consistency relationship don't need wrapping. When in doubt — if a partial failure would leave related rows inconsistent — still flag 🟡.

```php
// GOOD
DB::transaction(function () use ($data, $items) {
    $order = Order::create($data);
    $order->items()->createMany($items);
});
```

#### 4h. Multiple database connections

**Only when the project visibly uses more than one distinct database** (models declaring `$connection`, `DB::connection('...')` calls, or multiple connections in the diff) — otherwise this whole subsection is silent. **Read/write splits and replica aliases are one connection** — a `read`/`write` array inside a single connection config, or two named connections pointing at the same database, never fire these rules.

- A query or `join` that mixes tables from **different databases** — a cross-connection `join()`, or `whereHas`/`with` spanning models on different connections — 🟡 Warning. It works in dev where all databases share one host and breaks in production when they don't. Fetch from each connection separately and combine in PHP, or denormalize.
- New code querying a table through the **default** connection when the model/table demonstrably belongs to another database (its model declares `$connection`, or existing call sites consistently use `DB::connection('x')`) — 🟡 Warning; confirm-not-accuse ("this table appears to live on the `x` connection — confirm").
- Only flag what the diff shows — don't guess a table's home connection from its name.

---

### 5. Models

- Complex business logic or side effects inside a Model method — 🟡 Warning.
- HTTP concerns (`Request`, `response()`, `Auth` facade) inside a Model — 🟡 Warning.
- A method that issues its own Eloquent query instead of defining a scope — 🔵 Suggestion.
- Relationship method that contains eager-loading constraints (belongs in the Repository query, not the Model) — 🔵 Suggestion.
- `$guarded = []` without `$fillable` — see §4d (canonical rule).

---

### 6. Enums (`app/Enums/`)

Enums are value descriptors. Pure value-derivation on the enum is fine and encouraged — labels, colors, `canTransitionTo()`, grouping, `values()` / `labels()`, mapping helpers. Flag 🟡 Warning **only** side-effecting or cross-layer logic on the enum: a DB query, HTTP / `Auth` / `session` / `request` access, dispatching an event or job, or persistence. Those belong in a Service, not on the enum.

---

### 7. Correctness

- Null dereferences: `$model->relation->attribute` where `relation` could be `null` — 🔴 on a request path (uncaught 500), 🟡 if guarded or non-fatal.
- Off-by-one, wrong conditional, inverted boolean — 🟡 (🔴 if it causes data loss or corruption).
- Check-then-act races (`exists()` + `create()`) — see §8 (canonical).
- A value the **removed** lines null-checked, bounds-checked, or early-returned on is now used unchecked in the **added** lines — 🔴 if it can crash or corrupt, else 🟡. (Anchor to the removed guard; don't speculate about guards you can't see.)
- Semantically wrong HTTP status — `200` on a not-found or error path — 🟡. (The `201`-vs-`200`-on-create convention lives in §14.)
- Return type mismatches across code paths — 🟡.
- Loose comparison on identity-bearing values — `in_array()` / `array_search()` without strict `true`, or `==` / `!=` on a user- or DB-derived id, token, or hash — 🟡 (type-juggling / auth-bypass risk). Don't flag ordinary loose `==` on plainly same-typed values.
- Non-exhaustive `match` / `switch` over an enum with no `default` arm — 🟡 (a new case throws `UnhandledMatchError`; 🔴 on a hot path). Don't flag an already-exhaustive match.
- Native float arithmetic on currency/money values — 🔵 (use integer cents or a decimal type).

---

### 8. Data Integrity

- Multiple Eloquent writes without `DB::transaction()` — see §4g (canonical rule, 🟡 Warning).
- Check-then-act race conditions (canonical): `->exists()` + `->create()` → use `firstOrCreate()` / `updateOrCreate()` — 🟡 Warning.
- Read-modify-write on lost-update-prone data (balances, counters, inventory, seat/quota — illustrative) without `->lockForUpdate()` inside a transaction — 🟡 Warning. For a plain counter bump prefer an atomic `->increment()` / `->decrement()`; a *conditional* update still needs the lock or a DB constraint.
- A queued job / event dispatched **inside** a `DB::transaction()` closure without `afterCommit` (or the queue's `after_commit` config) — 🟡 Warning. The worker can pick up the job before the transaction commits and read stale/absent rows; use `->afterCommit()` or dispatch after the closure.

---

### 9. Performance

- **N+1** — §4b (🟡 Warning).
- **`->get()` then `->isEmpty()` / `->count()`** — 🔵 Suggestion — use `->exists()` / `->count()` on the builder **only when the result is used solely for the emptiness test and then discarded**. If the collection is iterated or returned afterwards, `->get()` + `->isEmpty()` is correct — don't flag it (swapping would force a redundant re-query).
- **`Http::` without `->timeout(N)`** — 🟡 Warning. Without a timeout the request can hang indefinitely under network issues, blocking the worker/request thread. Suggest `->timeout(30)`.
- **Full-table loads** — `Model::all()`, or an unbounded `->get()` / `->pluck()` with no `where` / `limit` / pagination, on an **unbounded, growing** table (users, orders, events, logs) — 🟡 Warning; use `->chunk()` / `->cursor()` / pagination. On a **mutable** table prefer `->chunkById()` over `->chunk()` (§16a); for very large workloads, chunk-and-queue (§16b). Don't flag it on an obviously small reference table (roles, statuses, countries, config) — absence of a growth signal is not a finding.
- **Over-selecting columns** — a large or hot-path read (`->get()` / `->cursor()` / `->paginate()` on an unbounded / growing table, per the full-table-loads rule above) that pulls every column via the Eloquent default when its consumer (API Resource, Blade view, export, `pluck`) uses only a few — 🟡 Warning; add an explicit `->select([...])` naming only the columns actually used, and drop heavy unused columns (TEXT / BLOB / JSON / serialized payloads) especially. **Guard against under-selecting — any `select([...])` MUST still include `id`, every foreign key the model's loaded relations / `with()` / `$with` rely on, and every column an accessor, `$appends`, or a cast reads. Omitting those silently breaks relations, appended attributes, and casts — do not push a `select()` that drops them.** Exempt: small reference tables (same growth-signal exemptions as full-table-loads), a query whose model is then mutated and `save()`d (it needs the full row), and reads feeding a Resource / response that exposes most columns. **If you cannot see from the diff which columns the consumer uses — or the model file (its `$appends`, casts, relations, `$with`) isn't in the diff — do not name a column list; at most suggest dropping a column that is demonstrably heavy and demonstrably unused, otherwise say nothing. Don't guess.** Separately, flag an explicit `->select('*')` / `DB::raw('select *')` as redundant (🔵) and `->get()->pluck('x')` — loads every column then plucks — as `->pluck('x')` on the builder (🔵).
- **Per-row writes in a loop** — a `save()` / `update()` / `delete()` executed once per iteration where a single mass `update()` / `delete()` / `upsert()` would do — 🟡 Warning. Exempt when each row genuinely needs its own logic or must fire model events.
- **Unnecessary re-fetch** — re-querying something already in scope — 🔵 Suggestion.

---

### 10. Error Handling & Resilience

- External HTTP calls with no `$response->successful()` check or try/catch — 🟡 Warning.
- A `catch` that neither logs, rethrows, nor handles the error — silent swallowing — 🟡 Warning. A catch that logs or genuinely handles is fine even if broad.
- **`report()` vs `Log` for a caught exception** — when a `catch` handles an exception locally (doesn't rethrow), prefer `report($e)` — it routes through the exception handler to the configured channels with the full stack/context — over `Log::error($e->getMessage())`, which flattens the exception to a bare string and drops the trace — 🔵 Suggestion. If you do log instead of `report()`, pass the exception rather than just its message (`Log::error('charge failed', ['exception' => $e])`) and match the level to severity (`error` for failures, `warning` / `info` for expected or diagnostic cases). Reserve plain `Log::info()` / `Log::debug()` for non-exception diagnostics. Don't flag a `catch` that rethrows or lets the exception bubble to the global handler — it's reported there already. A team that wants to **mandate** one path (e.g. always `report()`, never the `Log` facade) should encode that in its project `CLAUDE.md`.
- Missing fallback when a collection is empty but the next line assumes at least one element — 🟡 Warning.
- Decoding an external response with `->json()` / `json_decode()` and then indexing or iterating it without handling a malformed or empty body — 🟡 Warning (both return `null`, so `->json()['data']` then crashes).
- A `catch` that handles a failure but still returns a success response — HTTP `2xx`, `success: true`, or no error status at all — 🟡 Warning; return the correct `4xx` / `5xx` (throw an `HttpException`, `abort(5xx)`, or `response()->json([...], 5xx)`) so the caller can detect the failure instead of treating a broken call as OK. Exempt a catch that **genuinely recovers** — falls back to a valid value, retries successfully, or the failed step is optional — where success is the honest outcome; confirm-not-accuse when the recovery intent isn't clear from the diff. (Exposing the raw exception in the response body is the §3f half.)

---

### 11. Migrations (`database/migrations/`)

- **Non-null column added to an *existing* table without a default value or a two-step migration** (add nullable → backfill → make non-null) — 🔴 Critical. This will lock the table / fail on rows already present. Does **not** apply to columns inside a `Schema::create` (or a table created earlier in the same PR) — a brand-new table has no rows to break.
- **Model class referenced inside a migration** — 🔵 Suggestion. Prefer `DB::` or raw table names so the migration doesn't break if the Model is later renamed.
- **No `down()` method, or `down()` is empty** — 🔵 Suggestion. Rollback must be possible.
- **Missing index on a foreign key column** — 🔵 Suggestion.
- **Dropping a column/table or renaming a column on an existing table** (`dropColumn`, `dropTable`/`drop`, `renameColumn`) — 🟡 Warning. `down()` can recreate the structure but not the rows; confirm the data is expendable and the deploy is sequenced.
- **Narrowing a column type** — shortening a length, `text`→`string`, `bigInteger`→`integer`, cutting decimal precision — 🟡 Warning (silent truncation / mid-deploy failure on existing data).
- **Data-only migration — rows inserted/updated/deleted with no schema change** — 🟡 Warning. Migrations are for **schema (DDL)**; data belongs in an **idempotent seeder** (`updateOrCreate()` / `upsert()` / `firstOrCreate()` keyed on a stable identifier) — seeders are re-runnable, environment-targetable, and keep the migration history schema-only. Reference/lookup rows (roles, statuses, settings, permissions) are the classic case. **The legitimate exception:** a data change that must run **in lock-step with a schema change in the same deploy** — backfilling a new column before it's made non-null, or transforming rows into a structure a later migration depends on — belongs in the migration sequence; don't flag those.
- **New migration altering a table another migration in this same branch created or modified** — 🔵 Suggestion. While the earlier migration is unreleased, fold the change into it instead of stacking alter-migrations the branch itself introduced. (Never suggest editing a migration that has already merged/shipped — it has run on other environments.)

```php
// BAD — will lock table during deploy on large datasets
Schema::table('users', function (Blueprint $table) {
    $table->string('phone')->after('email');  // non-null, no default
});

// GOOD — two-step: nullable first, then backfill, then constrain
$table->string('phone')->nullable()->after('email');
```

```php
// BAD — data-only migration: runs once, buried in schema history
public function up(): void
{
    DB::table('roles')->insert(['name' => 'auditor', 'label' => 'Auditor']);
}

// GOOD — idempotent seeder: re-runnable, safe to re-seed any environment
public function run(): void
{
    Role::updateOrCreate(['name' => 'auditor'], ['label' => 'Auditor']);
}
```

---

### 12. Front-end framework quality (JS / TS)

**Detect the framework per changed front-end file first, then apply that framework's checklist plus the framework-agnostic checks (§12a).** Don't apply one framework's rules to another's file. Detection signals:

- **Vue** — `.vue` files, `<template>` / `<script setup>`, `defineComponent`, `ref()` / `reactive()`.
- **React** — `.jsx` / `.tsx` with JSX, `useState` / `useEffect` / other hooks, `import React`.
- **Angular** — `*.component.ts`, `@Component` / `@Injectable` decorators, `@angular/*` imports, `*ngIf` / `*ngFor` templates.
- **Svelte** — `.svelte` files.
- **Vanilla / unknown** — plain `.js` / `.ts` with none of the above.

For a framework **not enumerated below** (Angular, Svelte, Solid, Alpine, …), apply **that framework's own well-known best practices** at the appropriate severity — component-lifecycle cleanup, state immutability, list-key/tracking, effect/reactive-dependency correctness, XSS sinks, subscription/listener leaks — alongside §12a. The team's project `CLAUDE.md` can add framework-specific rules.

#### 12a. Framework-agnostic (any JS / TS)

- **Unsanitised HTML injection** — `el.innerHTML =`, Vue `v-html`, React `dangerouslySetInnerHTML`, Angular `[innerHTML]` — with user-supplied input — 🔴 Critical (also §3f, §15c).
- **Listener / subscription / timer added without matching cleanup** on teardown — 🔵 Suggestion (memory leak).
- **Direct DOM manipulation** (`document.querySelector`, manual node mutation) inside a component — 🔵 Suggestion; use the framework's ref mechanism.
- **`fetch` / `axios` / HTTP call with no error handling** — 🟡 Warning. Exempt a call through the app's central configured client whose **interceptors already handle errors** — that's the pattern working as designed. When the bypass bullet below also fires on the same line, post one finding (the bypass — routing through the shared instance usually fixes both).
- **Bypassing the app's configured HTTP client** — a fresh `axios.create()`, raw `fetch()`, or ad-hoc `XMLHttpRequest` for an **internal API call** when the codebase routes requests through a central configured instance (base URL, auth/CSRF headers, loading/error interceptors — e.g. a `bootstrap/axios.js`) — 🟡 Warning; import the shared instance, a bypass silently drops every interceptor. Only flag when a central instance demonstrably exists (visible in the repo or the diff imports one elsewhere). Exempt calls to **third-party** endpoints that must not carry the app's headers/credentials.
- **Missing loading / error state** for an async operation surfaced in the UI — 🔵 Suggestion.
- **Native `alert()` / `confirm()` / `prompt()` in app code** — 🔵 Suggestion (🟡 if the codebase has an established dialog/notification system the diff ignores). They block the event loop, can't be styled, and break async confirm flows — use the app's notification/dialog component (toast library, SweetAlert, modal system). Exempt `beforeunload` / navigation-guard handlers (custom modals are impossible mid-unload) and throwaway scripts that won't ship.
- **Front-end literals duplicating backend enum values** — hardcoded status/type/role strings in JS that mirror a backend enum (`'pending'`, `'super-admin'`, `'appraisal'`) — 🔵 Suggestion **when the project has a shared constants module** (e.g. `constants/*.js` mirroring PHP enums) that the diff bypasses; add the value to the module if it's missing, then import it. If no such module exists, the literal is just §2i (magic values) — don't invent a convention.
- **Second date-handling stack** — raw `toLocaleDateString()` / `new Date()` formatting or a newly-introduced date library in a codebase that routes date work through a central helper or a single established library — 🔵 Suggestion; use the project's wrapper (it owns nil-safety, parsing, and locale). Only flag when the central helper demonstrably exists; don't flag date *math* or non-display parsing, and don't flag test files building expected strings.
- **Secrets committed in front-end/bundle code** — see §3i.

#### 12b. Vue

- **Missing `:key` in `v-for`** — 🟡 Warning.
- **`:key="index"`** in a list that can reorder — 🔵 Suggestion.
- **`v-if` + `v-for` on the same element** — 🔵 Suggestion.
- **Bypassing the store's defined action to write state** — a Vuex `state.x = y` mutation outside a mutation, or a Pinia store patched directly where an action exists — 🟡 Warning.
- **Mutating a prop** inside a component (`this.prop = …` / assigning to a `defineProps` value) — 🟡 Warning; emit an event or use a local copy.
- **Losing reactivity by destructuring a `reactive()` object** (`const { x } = reactive(...)`) — 🔵 Suggestion; use `toRefs()`.
- **Unscoped `<style>`** — 🔵 Suggestion.

#### 12c. React

- **Missing `key`, or `key={index}` in a reorderable list**, on elements rendered from `.map(...)` — 🟡 Warning for missing, 🔵 for index-as-key.
- **`useEffect` with a missing/incorrect dependency array**, or an effect that subscribes / adds a listener / starts a timer with no cleanup return — 🟡 Warning.
- **Directly mutating state** — `state.x = …`, `arr.push()` on a state value — instead of `setState` / an immutable update — 🟡 Warning.
- **Hooks called conditionally or inside a loop/nested function** (violates the Rules of Hooks) — 🟡 Warning.
- **New inline object / array / function passed as a prop on a hot path** forcing child re-renders — 🔵 Suggestion (memoize with `useMemo` / `useCallback`).
- **Deriving state into `useState` + `useEffect`** where it could be computed during render — 🔵 Suggestion.

---

### 13. Testing Signals

#### Untestable patterns (flag on the code, not on missing tests)

- `new ClassName()` inside business logic — 🔵 Suggestion, prevents mocking (see §4f).
- HTTP helpers inside Services — 🟡 Warning (see §1b for the canonical list).
- `$this->withoutExceptionHandling()` committed — 🟡 Warning (debugging aid must not be merged).

#### Test quality

- **Outbound HTTP in a test without `Http::fake()`** (or the project's HTTP-fake helper) — 🟡 Warning. Stray requests make tests flaky and environment-dependent.
- **New outbound HTTP call in app code with no fake in its covering test** — the diff adds an `Http::` / SDK / API call on a tested path, and the test touching that path (in the diff) adds no corresponding `Http::fake()` / fake helper — 🟡 Warning. Where the suite runs `Http::preventStrayRequests()` this fails every test on the path; elsewhere it silently hits the real network from CI. If no test in the diff covers the new call, treat it as the missing-test signal instead — don't double-flag. When this and the test-side bullet above both apply to the same diff, post **one** finding, anchored to the test.
- **Testing a private/protected method via reflection** — 🟡 Warning (test observable behaviour through the public API).
- **Test with no assertions** — 🔵 Suggestion (passes vacuously).
- **Tautological / constant assertions** — `assertTrue(true)`, `assertEquals($x, $x)` — 🔵 Suggestion (proves nothing).
- **Unconditional `markTestSkipped()` / `markTestIncomplete()`** with no reason — 🔵 Suggestion (a permanently green skip).
- **`assertStatus(200)` with no body assertion** — 🔵 Suggestion.
- **DB records created without `RefreshDatabase`** (or the project's equivalent trait) — 🔵 Suggestion (risks test pollution).
- **`Mockery::mock()` used directly** instead of Laravel's `mock(ClassName::class)` — 🔵 Suggestion (plain Mockery doesn't bind into the container).
- **Protected-route test with no authenticated user** — no `actingAs()` / `Sanctum::actingAs()` (or a project `signIn()` helper if present) — 🔵 Suggestion.
- **No unauthenticated path test** for a protected route — 🔵 Suggestion.

**Feature test vs Unit test:** feature tests when the path touches HTTP, database, or external services; unit tests for pure logic in a Service, DTO, or utility. If flagged, 🔵 Suggestion: a unit test that mocks the repository for logic that really exercises a query can hide a query bug — a feature test would catch it.

---

### 14. API Design

- `POST` creating a resource returning `200` instead of `201` — 🔵 Suggestion.
- A `GET` route whose handler mutates state — persists, updates, deletes, or dispatches a job (a `store`/`update`/`destroy`-style action behind `GET`) — 🟡 Warning. GET must be safe/idempotent; it's CSRF-exempt and prefetch/cache-unsafe. Only flag when the mutation is observable at the route/handler.
- Collection endpoint returning the full result set with no `paginate()` / `limit` — 🔵 Suggestion ("add pagination unless the set is bounded"); escalate to 🟡 on a concrete unbounded-growth signal (results filtered/ordered by user input, or an append-only/log/comment model). (Perf angle in §9.)
- API Resource over-exposing internal design detail — `created_at`, pivot columns, internal auto-increment IDs — 🟡 Warning. (Credential/session fields like `password`/`remember_token` are the 🔴 case in §3f, not here.)
- A new/changed Resource whose envelope shape (`data` / `meta` / `errors` wrapping) differs from a **sibling Resource also in the diff** — 🔵 Suggestion. Don't guess the canonical envelope from unchanged code.

---

### 15. Blade views (`resources/views/`)

Views are presentation only. Anything that queries data, decides business rules, or runs PHP belongs in a controller, service, or view-composer.

#### 15a. No business logic in views

- Direct Eloquent queries (`User::find(...)`, `$x->orders()->count()`) inside Blade — 🟡 Warning. Pass the data from the controller / view-composer.
- `@php ... @endphp` blocks **containing queries, business logic, or side effects** — 🟡 Warning; lift it out. A trivial `@php $i = 0; @endphp` loop counter or `@php use App\Enum; @endphp` import is fine — don't flag those.
- Multi-branch logic, calculations, formatting decisions — 🔵 Suggestion. Move to a helper, accessor, or view-composer.

```blade
{{-- BAD --}}
@php($orders = $user->orders()->where('status', 'paid')->get())
@foreach ($orders as $order) ... @endforeach

{{-- GOOD — controller passes $paidOrders --}}
@foreach ($paidOrders as $order) ... @endforeach
```

#### 15b. N+1 in `@foreach`

Same rule as §4b — accessing a relation inside a loop without prior eager loading is 🟡 Warning. The fix lives in the controller/repository, not the view.

```blade
{{-- BAD: one query per user --}}
@foreach ($users as $user)
    {{ $user->profile->bio }}
@endforeach

{{-- Controller must eager-load: User::with('profile')->get() --}}
```

#### 15c. XSS — beyond `{!! !!}`

- `{!! $var !!}` with user-supplied content — 🔴 Critical (also §3f).
- `href="{{ $url }}"` or `src="{{ $url }}"` where the value is a user-supplied URL — 🟡 Warning. `{{ }}` escapes HTML but `javascript:foo()` still executes. Validate the scheme or whitelist URLs. Do not flag framework-derived URLs (`route()`, `asset()`, `url()`, config values).
- Inline JS event handlers carrying user data (`onclick="doThing('{{ $msg }}')"`) — 🟡 Warning. Use unobtrusive JS. To hand data to JS safely, use `Js::from($msg)` **inside a `<script>` block**, or an HTML-escaped data attribute (`data-msg="{{ json_encode($msg) }}"`, which `{{ }}` escapes). Do **not** put raw `@json($msg)` in an HTML attribute — `@json` is not attribute-escaped, so `"` in the value breaks out of the attribute and is itself an XSS vector.
- `style="{{ $userValue }}"` — 🔵 Suggestion. Style injection can leak data (`background-image: url(...)`) or break layout.

#### 15d. CSRF on state-changing forms

`<form method="POST" …>` (including spoofed `PUT`/`PATCH`/`DELETE` via `@method`) without `@csrf` — 🟡 Warning. The middleware will reject it at runtime; this is a bug-in-waiting.

#### 15e. Auth / Request / DB facades in views

`request()`, `auth()->user()`, `DB::`, raw query builders called directly from Blade — 🔵 Suggestion. Pass through the controller or a view-composer for testability and to keep layering clean.

`@auth` / `@guest` / `auth()->check()` for conditional rendering are documented patterns and fine.

#### 15f. Localisation

If the project uses `__()` / `trans()` elsewhere, hardcoded user-facing strings in new Blade content — 🔵 Suggestion. Apply only when the surrounding codebase is already localised.

#### 15g. Component extraction

A single Blade file over ~200 lines, or a `@foreach` body of **complex** markup over ~40 lines — 🔵 Suggestion. Extract a Blade component (`<x-…>`) or partial via `@include`. Don't flag a long but flat table/list; flag when the body has meaningful nesting or conditionals.

#### 15h. Dynamic `@include` paths

`@include($var)` where `$var` could be influenced by request input — 🔴 Critical. Path-traversal / arbitrary view rendering risk.

---

### 16. Scalability & Large Dataset Processing

Review every data-touching change as if it will run in production against **10M+ rows**, millions of queued jobs, and **multiple queue workers across multiple app servers executing concurrently**. Code that is correct and fast against a dev seed of 100 rows can exhaust memory, lock a table, or corrupt state at scale. Before approving, ask: *would this hold at 10M rows? Will it exhaust memory? Can it run safely on concurrent workers? Is it idempotent and retry-safe? Does it needlessly block a web request? Does it scale horizontally by just adding workers?*

When you flag something here, don't just cite the rule — in plain language name **at what scale it starts to bite** and **the trade-off of the fix**, so the developer understands why it matters (correctness first, then scalability).

Most single-line scalability smells already have canonical rules — apply the scale lens and point at them rather than re-flagging:
- **Full-dataset loads into memory** — `Model::all()` / unbounded `->get()` / `->pluck()` on a growing table — §9 (canonical, 🟡). Recommend `->chunkById()` / `->cursor()` / `->lazy()` / pagination; `cursor()`/`lazy()` stream one hydrated model at a time when you must touch every row but not mutate the driving table.
- **Per-row writes in a loop** — batch with `insert()` / `upsert()` / mass `update()` — §9 (canonical, 🟡).
- **N+1 reads** — §4b.
- **Heavy synchronous work on a request path** — imports, exports, PDF/image generation, email, notifications, external API calls, report generation, search/index sync, cache warming/rebuilds — belongs on a queue: §4e (canonical). Moving it off the request improves responsiveness, fault tolerance (retries without user re-submit), and scalability (throughput scales with workers, not web nodes).
- **Multi-write transactions** — §4g / §8. **Check-then-act races / `lockForUpdate`** — §8. **`Http::` timeouts** — §9.

The rules below are the scale-sensitive cases — large datasets, queued workloads, hot reads, shared file storage — **not** covered above.

#### 16a. `chunkById()` over `chunk()` on mutable tables — 🟡 Warning

`chunk()` paginates with `LIMIT`/`OFFSET` and re-runs the query per page. If rows are **inserted or deleted** in the range while iterating — likely when other workers/requests write the same table, or when the loop body itself mutates the driving rows — the OFFSET shifts and records get **skipped or processed twice**. `chunkById()` keyset-paginates on the primary key (`WHERE id > lastId`) and is immune. Prefer it whenever the table is mutable during processing, and **always** when the loop body updates or deletes the rows it is iterating.

```php
// BAD — deleting rows shifts the OFFSET → later rows get skipped
User::where('active', false)->chunk(1000, function ($users) {
    foreach ($users as $user) { $user->delete(); }
});

// GOOD — keyset pagination, unaffected by inserts/deletes
User::where('active', false)->chunkById(1000, function ($users) {
    foreach ($users as $user) { $user->delete(); }
});
```

Judgement: `chunk()` over an append-only / immutable snapshot, or one fully isolated in a transaction, is acceptable — 🔵 Suggestion at most.

#### 16b. Chunk-and-queue for large workloads; avoid monolithic commands — 🔵 Suggestion

A scheduled command or Service that discovers **and** processes a large dataset in one synchronous pass can't scale past a single process, loses all progress on failure, and can't parallelise. Separate **orchestration from execution**: read IDs in chunks and dispatch one small, independent Job per chunk — the fleet then scales horizontally just by adding workers. Structure long-running workflows as: **1) discover work → 2) dispatch work → 3) process work → 4) aggregate results → 5) finalise.**

```php
// BAD — monolithic: one process does everything, no retry granularity
public function handle(): void
{
    foreach (User::all() as $user) {     // also §9 full-table load
        $this->reindex($user);           // dies at row 4M → restart from zero
    }
}

// GOOD — orchestrator dispatches per-chunk jobs; workers process in parallel
User::select('id')->chunkById(1000, function ($users) {
    ReindexUsers::dispatch($users->pluck('id')->all());
});
```

Pass **IDs or ID ranges**, never a serialised Eloquent collection — serialising models bloats the payload, freezes a stale attribute snapshot, and worsens as the row count grows. Keep jobs small and independently retryable; use `Bus::batch()` when you need completion/aggregation callbacks across the chunks.

#### 16c. Job idempotency — 🟡 Warning

Queues guarantee *at-least-once*, not exactly-once, delivery: any Job can run **more than once** (retry after timeout, worker crash after the work but before ack, manual replay). A Job whose re-execution creates **duplicate rows, duplicate emails, duplicate external charges/API calls, or double-applied state** is a correctness bug. Make the effect idempotent:
- `updateOrCreate()` / `firstOrCreate()` / `upsert()` instead of `create()` (see also §7 check-then-act).
- a unique constraint / unique key so a replay collides instead of duplicating.
- a processed-marker or dedupe key checked before any non-transactional side effect (emails, payments, webhooks).

```php
// BAD — a retry inserts a second payment row and re-sends the receipt
public function handle(): void
{
    Payment::create(['order_id' => $this->orderId, /* ... */]);
    Mail::to($this->order->user)->send(new ReceiptMail($this->order));
}

// GOOD — replay-safe: unique-keyed upsert + guarded side effect
public function handle(): void
{
    $payment = Payment::updateOrCreate(
        ['idempotency_key' => $this->key],
        ['order_id' => $this->orderId, /* ... */],
    );

    if ($payment->wasRecentlyCreated) {
        Mail::to($this->order->user)->send(new ReceiptMail($this->order));
    }
}
```

#### 16d. Retry safety — small, independently-retryable units — 🔵 Suggestion

Assume every Job, command, and external call can fail partway. A failure should require retrying **one small unit of work**, not restarting a whole batch — and a retry must not discard progress already committed. Flag designs where a mid-run failure re-does or loses large amounts of work: split the work (§16b), make each unit idempotent (§16c), and commit progress incrementally (e.g. mark each chunk done) so a retry resumes rather than restarts. Set `$tries` / `backoff` / `retryUntil` and a `failed()` handler where transient failures are expected.

#### 16e. Concurrency — assume many workers run at once — 🟡 Warning

Every Job and request may execute **simultaneously across many workers and servers**. Read-modify-write in PHP is not atomic and races under concurrency (canonical check-then-act / `lockForUpdate`: §8). Flag non-atomic updates and shared-resource races, and recommend the fitting primitive:
- **atomic DB operations** — `->increment()` / `->decrement()`, `whereIn(...)->update([...])`, `DB::raw('col + 1')` — instead of read-into-PHP-then-save.
- **transaction + `lockForUpdate()`** (pessimistic) or a `version`-column check (optimistic) for read-then-modify on a row.
- **`ShouldBeUnique`** on a Job that must not run twice concurrently for the same key.
- **`Cache::lock()`** (a distributed lock) to serialise a critical section across workers.
- **`Http::pool()`** to fan out independent external calls concurrently instead of serially.

```php
// BAD — lost update: two workers read 10, both write 11
$product = Product::find($id);
$product->stock = $product->stock - 1;
$product->save();

// GOOD — atomic decrement, no race, guards against overselling
Product::where('id', $id)->where('stock', '>', 0)->decrement('stock');
```

#### 16f. Cache hot, expensive reads in Redis — 🔵 Suggestion

When the diff adds or reworks a read that is **served repeatedly with the same result** and **costs enough to be worth not repeating** — either expensive per call (a heavy aggregate / multi-join) **or** cheap per call but on a **hot per-request path** where the aggregate DB load adds up (settings, lookups, per-item reads in a listing) — suggest caching it in Redis via Laravel's cache (`Cache::remember()`). Frequency is a first-class trigger here, not just per-call expense. Judge *hot* from context, not just the code: the card description and PR context often say what the change is for — a dashboard, homepage widget, public listing, report, or navigation menu implies a high-traffic read path; an admin one-off does not. Typical candidates:

- aggregate/report queries (joins + `groupBy` + aggregates) feeding dashboards or widgets;
- reference/lookup data read on many requests (settings, menus, categories, feature flags);
- expensive derived values recomputed per request (rankings, counts over large tables);
- calls to slow external APIs whose response is stable over minutes.

```php
// BAD — heavy aggregate recomputed on every dashboard hit
$stats = Order::whereYear('created_at', now()->year)
    ->selectRaw('status, count(*) as total, sum(amount) as revenue')
    ->groupBy('status')
    ->get();

// GOOD — computed once per 10 minutes, served from Redis after that
$stats = Cache::remember('dashboard:order-stats:'.now()->year, 600, fn () =>
    Order::whereYear('created_at', now()->year)
        ->selectRaw('status, count(*) as total, sum(amount) as revenue')
        ->groupBy('status')
        ->get()
);
```

A useful suggestion names the three cache decisions, not just "cache this": the **key** (include every parameter that changes the result — tenant, user, filters, date), the **TTL / staleness budget** the business can tolerate, and the **invalidation path** (TTL expiry, or `Cache::forget()` / a model observer when the underlying rows change).

Judgement — do **not** suggest caching when:
- the read is a trivial single-row indexed lookup (e.g. `find($id)` on a primary key) — the cache round-trip costs about as much as the query and adds staleness risk for no real saving; **frequency alone does not change this** — a hot path only justifies a cache when each call does non-trivial work or the aggregate DB load is the actual problem;
- the result must be **read-after-write fresh** (balances, stock levels, authorization state) and no invalidation hook exists — a stale cache there is a correctness bug, not an optimisation;
- the key cardinality is unbounded (per-user × per-filter × per-page keys) — that's Redis memory pressure, not a cache;
- the card/code indicates a rarely-hit path (admin tooling, one-off command);
- the value is already cached upstream or wrapped in `remember()`.

Fix first, cache second: caching over an N+1 or a full-table load hides the defect until the first cold miss — flag the underlying smell (§4b / §9) as the primary finding and the cache as a follow-up.

#### 16g. Files, images, and assets belong in S3, not on the server's disk — 🟡 Warning

Persistent files written to the **local filesystem** are a standing production problem in this stack: app-server disks have repeatedly bloated toward full, and a file written to one server's disk is invisible to the other servers — and gone after a redeploy or autoscale. User uploads, images, and generated output (PDFs, exports, reports) belong in **S3** via Laravel's filesystem abstraction.

Flag when the diff writes a **persistent** file to a local path:

- `->store(...)` / `->storeAs(...)` / `Storage::put(...)` targeting the `local` or `public` disk for a user upload or generated output;
- `move_uploaded_file()`, `File::put()`, `file_put_contents()`, or `->move(...)` writing under `public_path()` / `storage_path()`;
- a file-producing library (PDF/report/image generation) configured to emit into a local directory with no upload step afterwards.

```php
// BAD — lands on one server's disk: bloats storage, invisible to other nodes
$request->file('avatar')->store('avatars', 'public');

// GOOD — object storage; serve via URL (temporaryUrl for private files)
$path = $request->file('avatar')->store('avatars', 's3');
$url  = Storage::disk('s3')->temporaryUrl($path, now()->addMinutes(10));

// GOOD — this codebase's Asset::storage() helper returns the S3-backed disk;
// prefer it over naming the disk inline
Asset::storage()->putFileAs('avatars', $request->file('avatar'), $filename);
```

When suggesting the fix, recommend the project's **`Asset::storage()`** helper as the idiomatic entry point — it centralises the disk choice instead of scattering `'s3'` string literals.

**Temp files are fine — if they're actually temporary.** Some work legitimately needs a local file (image manipulation, zip assembly, buffering a download before upload). Write it under `sys_get_temp_dir()` / `tempnam()` — never a persistent app path — and **guarantee cleanup on every exit path, including failure** (a `finally` block). A temp file created with no visible deletion is 🟡 on its own: leaked temp files are exactly how the disks got bloated.

```php
// GOOD — local scratch file, result uploaded to S3, cleanup guaranteed
$tmp = tempnam(sys_get_temp_dir(), 'export_');
try {
    $this->generateCsv($tmp);
    Asset::storage()->putFileAs('exports', new File($tmp), $filename);
} finally {
    @unlink($tmp);
}
```

Judgement — do **not** flag:

- writes through **`Asset::storage()`** (S3-backed by definition), `Storage::disk('s3')` / another cloud disk, or a diskless `->store('path')` when the **default disk** may already be S3 — check `config/filesystems.php` if visible; if not, phrase as a question ("confirm the default disk is s3") rather than an assertion;
- framework-managed local paths — caches, compiled views, sessions, logs;
- genuinely ephemeral scratch files with visible failure-safe cleanup;
- test code writing to `Storage::fake()` or a local disk.

---

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
