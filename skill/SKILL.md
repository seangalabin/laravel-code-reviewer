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

The `.py` scripts (`scan_diff.py`, `check_resolved.py`, `check_dismissals.py`, `check_replies.py`, `update_resolved.py`, `post_reply.py`, `aggregate_stats.py`) are byte-identical across platforms — only the launcher differs (`python`). Each `.ps1` accepts the same arguments and reads the same `.ai-review/target.json` as its `.sh` counterpart. The one command that doesn't follow the table mechanically is `post_review.sh` (it reads findings on stdin via a heredoc) — its Windows form is shown in **Posting the review**.

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

1. **Find the ticket reference.** Look, in order, for a pattern like `[A-Z]+-\d+`:
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

4. **Use this as reference context for Step 1, not as a new scope.** The Scope rule below is unchanged — you still review only what the diff touched. The card informs **judgment**:
   - Does the diff address the stated problem, or something adjacent?
   - Does it satisfy the explicit acceptance criteria?
   - Does it scope-creep beyond what the card asks for? (Surface scope-creep as 🔵 Suggestion — out-of-scope changes belong in a separate PR.)
   - Are obvious card requirements missing from the diff? (Surface as 🟡 Warning — likely incomplete work.)

5. **No ticket detected** → print `No ticket reference detected — reviewing diff against develop only.` and continue. The skill still works without a card; it just loses the "right problem" signal.

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

`post_reply.py` appends a hidden `<!-- ai-review:reply -->` marker so the bot recognises its own answer and never replies to it again. **Windows mode:** pipe the body into `python .claude/skills/code-reviewer/scripts/post_reply.py --parent-id={reply_id}` with a here-string, exactly like `post_review.ps1` in **Posting the review**.

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

### Step 3 — Learning summary (private — author only, never posted)

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

## Review lens

Work through these dimensions in order. If the project has `.coderabbit.yaml` or `CLAUDE.md` rules, apply those first — these dimensions extend them.

---

### 1. Architecture & Layering (first-class concern)

The repo enforces a **Controller → Service → Repository → Model** call graph.

**Permitted shortcuts:**
- Controller → Repository is acceptable for **read-only** lookups.
- Controller → Repository for **write** operations is 🟡 Warning — writes must go through a Service to keep transactions and side-effects in one place.

Every violation of the layering rules below is at minimum 🟡 Warning.

#### 1a. Controller responsibilities

Controllers are HTTP adapters only. They must:
- Receive a typed `FormRequest` (validation already done)
- Call one Service method (or a Repository for simple reads) with plain values or a DTO
- Return an API Resource or a paginated collection Resource

Controllers must NOT:
- Contain business logic (conditionals, calculations, multi-step workflows)
- Issue Eloquent queries or call Model static methods directly — 🟡 Warning
- Call `$request->validate(...)` inline — use a `FormRequest` — 🟡 Warning
- Contain `if ($user->role === ...)` or any manual authorization — use Policies/Gates — 🟡 Warning
- Return `$model->toArray()`, `response()->json($model)`, or a raw array — use an API Resource — 🟡 Warning
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
- Be HTTP-agnostic: no `auth()`, `Auth::`, `redirect()`, `response()`, `session()` — 🟡 Warning
- Be injectable via the service container — `new ServiceClass()` inside another Service is 🔵 Suggestion

Service method length: flag at **30+ lines** as 🔵 Suggestion.

#### 1c. Repository responsibilities

Repositories own all Eloquent/query logic. They must:
- Return typed objects (`Model`, `Collection`, `?Model`) — returning a plain `array` is 🔵 Suggestion
- Contain no business logic, no HTTP concerns — 🟡 Warning
- Use Eloquent scopes for reusable filter chains — a very long query chain where a named scope would help readability is 🔵 Suggestion
- Avoid eager-loading constraints inside relationship methods — those belong in the Repository query, not on the Model

**Repository granularity — one per aggregate root, not one per Model.** A Repository owns an entire domain aggregate. Models that exist only as children of another aggregate root (data / details / items / attachments / metadata rows with a FK to a parent and no independent lifecycle outside it) belong inside the parent's Repository — do **not** create a separate Repository for them.

- Adding a new `XYRepository` when `XRepository` already exists, and `XY` is a child of `X` (FK to `X`, no standalone use) — 🔵 Suggestion. The queries belong in `XRepository`; this is a structural refactor, not a runtime bug.
- A Service or Controller querying a child Model directly (via the Model facade or bypassing the parent Repository entirely) when the parent Repository exists — 🟡 Warning. This is a real layering violation — add the method to the parent Repository instead.
- Naming-heuristic guidance for the reviewer: if a new Repository's name shares a prefix with an existing Repository (e.g. `Appraisal`/`AppraisalData`, `Order`/`OrderItem`, `Property`/`PropertyMedia`), consider whether it should be folded. Apply judgement — many shared-prefix pairs are genuinely independent (`Product`/`ProductCategory`, `Payment`/`PaymentMethod`, `User`/`UserGroup`).

```php
// BAD — fragments the Appraisal aggregate across two repositories
class AppraisalDataRepository {
    public function forAppraisal(int $appraisalId): Collection { ... }
}

// GOOD — AppraisalData lives on the Appraisal aggregate
class AppraisalRepository {
    public function dataFor(int $appraisalId): Collection { ... }
    public function withData(int $appraisalId): ?Appraisal { ... }
}
```

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

Every Controller method that accepts user input must type-hint a dedicated `FormRequest` subclass. Inline `$request->validate([...])` in a Controller or Service is 🟡 Warning. A `FormRequest` with an empty `rules()` method is also 🟡 Warning.

#### 1f. Console Commands

`handle()` in a Console Command is a thin CLI adapter — it must delegate to a Service or Repository. Direct Eloquent queries or business logic inside `handle()` is 🟡 Warning. Use `$this->info()` / `$this->error()` for output (not `echo`) — 🔵 Suggestion.

---

### 2. PSR-12 & Code Standards

#### 2a. `declare(strict_types=1)`

All new PHP files under `app/` must open with `declare(strict_types=1)` as the first statement after `<?php`. Flag as 🔵 Suggestion.

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
| Model names | Singular | `User`, `Order` |

---

### 3. Security

#### 3a. Authorization — Policies and Gates

Manual role/permission checks in Controllers or Services are 🟡 Warning:

```php
// BAD
if (auth()->user()->role === 'admin') { ... }
if ($request->user()->is_admin) { ... }

// GOOD
$this->authorize('update', $user);
Gate::authorize('update-user', $user);
```

Every `FormRequest::authorize()` that unconditionally returns `true` without a comment explaining why (e.g., genuinely public endpoint) is 🔵 Suggestion.

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

🔴 Critical:

```php
// BAD — injectable
->whereRaw("name = '$name'")
DB::statement("DELETE FROM users WHERE id = $id")

// GOOD
->whereRaw('name = ?', [$name])
```

#### 3d. Insecure direct object reference (IDOR)

🟡 Warning — any controller that fetches a resource by ID without scoping to the authenticated user or checking a Policy:

```php
// BAD
$order = Order::findOrFail($request->order_id);

// GOOD
$order = auth()->user()->orders()->findOrFail($request->order_id);
```

#### 3e. File upload security

🟡 Warning — a FormRequest that accepts file uploads without **both** a type allow-list and a size cap. Either `mimes:` or `mimetypes:` is acceptable (both sniff actual file contents):

```php
// BAD
'photo' => 'required|file'

// GOOD — either form is acceptable
'photo' => 'required|image|mimes:jpeg,png,webp|max:5120'
'photo' => 'required|image|mimetypes:image/jpeg,image/png|max:5120'
```

#### 3f. Sensitive data leaks

- `{!! $var !!}` in Blade or `v-html` in Vue where value could be user-supplied — 🔴 Critical.
- API Resources that return `password`, `remember_token`, `api_token`, or raw pivot data — 🟡 Warning.
- `Log::info()` / `Log::error()` that logs a full request body, password, or token — 🟡 Warning.

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
- `error_log()`, `var_dump()`, `print_r()`, `echo` used for logging — use `Log::info()` / `Log::error()` / `Log::debug()`.
- `$_SERVER`, `$_ENV`, `$_GET`, `$_POST`, `$_REQUEST` — use Laravel helpers (`request()`, `config()`).
- Hardcoded credentials, API keys, or magic numbers that belong in `config/` or `.env`.

---

### 4. Laravel Best Practices

#### 4a. API Resources — no raw `toArray()` or model-to-JSON

Every JSON response must use a dedicated API Resource. Raw `->toArray()`, `response()->json($model)`, or `$model->toJson()` in a Controller are 🟡 Warning:

```php
// BAD
return response()->json($user->toArray());

// GOOD
return new UserResource($user);
return UserResource::collection($users);
```

Inside an API Resource's `toArray()`: no DB queries, no Service calls — 🟡 Warning (Resources transform already-loaded data only). Use `$this->whenLoaded('relation')` for related models — omitting it causes N+1 queries when the relation was not eager-loaded — 🟡 Warning (same gravity as §4b).

FormRequest validation: flag raw string rules where a `Rule` object would be safer (e.g. `Rule::unique()`, `Rule::exists()`) — 🔵 Suggestion.

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

// BAD — same shape outside a loop, any parent/child pair
$invoice = Invoice::find($id);
$client  = Client::find($invoice->client_id);

// BAD — child-side: looking up the parent by FK
$post   = Post::find($id);
$author = User::find($post->author_id);

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

The rule applies to **every** Eloquent model and relationship in the codebase — `Order`/`Customer`, `Invoice`/`Item`, `Post`/`Comment`, `Project`/`Task`, `Tenant`/`Booking`, anything. Treat the BAD/GOOD pairs above as the *shape* to recognise, not as an exhaustive whitelist of models.

**If the relationship isn't defined on the Model yet, the fix is to define it** — `public function customer(): BelongsTo`, `public function items(): HasMany`, `public function author(): BelongsTo`, etc. — not to keep manually joining via `Model::find($fk)` or `Model::where('fk_column', …)`.

#### 4c. Eloquent scopes

Repeated query chains belong in a named local scope. Flag duplicated filter chains as 🔵 Suggestion.

#### 4d. Fillable / guarded hygiene

`$guarded = []` without an explicit `$fillable` — 🔵 Suggestion (flag, suggest `$fillable`).

#### 4e. Jobs, Events, Listeners, Observers — when to require them

Flag as 🟡 Warning when inline Controller/Service code should be extracted:

**Use a Job when:** work takes >~500ms, needs retry logic, or blocks the web request (email, PDF, external API calls).

**Use an Event + Listener when:** one action triggers multiple unrelated side effects.

**Use an Observer when:** the same Model lifecycle hook is handled in multiple places.

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

#### 4g. `DB::transaction()` for multi-write paths (canonical)

Any code path that issues two or more write queries must be wrapped in `DB::transaction()`. A missing transaction on a Service multi-write path is 🟡 Warning — without it, the second write failing leaves the first committed and the dataset in an inconsistent state:

```php
// GOOD
DB::transaction(function () use ($data, $items) {
    $order = Order::create($data);
    $order->items()->createMany($items);
});
```

---

### 5. Models

- Complex business logic or side effects inside a Model method — 🟡 Warning.
- HTTP concerns (`Request`, `response()`, `Auth` facade) inside a Model — 🟡 Warning.
- A method that issues its own Eloquent query instead of defining a scope — 🔵 Suggestion.
- Relationship method that contains eager-loading constraints (belongs in the Repository query, not the Model) — 🔵 Suggestion.
- `$guarded = []` without `$fillable` — see §4d (canonical rule).

---

### 6. Enums (`app/Enums/`)

Business logic beyond label, color, or helper methods on the enum itself is 🟡 Warning. Enums are value descriptors only.

---

### 7. Correctness

- Null dereferences: `$model->relation->attribute` where `relation` could be `null`.
- Off-by-one, wrong conditional, inverted boolean.
- `firstOrCreate` vs separate `exists() + create()` — the latter is a race condition.
- Missing guard after a refactor.
- Incorrect HTTP status codes (`200` for created, `200` for not-found).
- Return type mismatches across code paths.

---

### 8. Data Integrity

- Multiple Eloquent writes without `DB::transaction()` — see §4g (canonical rule, 🟡 Warning).
- Check-then-act race conditions: `->exists()` + `->create()` → use `firstOrCreate()`.
- Missing `->lockForUpdate()` on rows read-then-modified concurrently.

---

### 9. Performance

- **N+1** — §4b. Always 🟡 Warning.
- **`->get()` then `->isEmpty()`** — use `->exists()` or `->count()` on the query builder.
- **`Http::` without `->timeout(N)`** — 🟡 Warning. Without a timeout the request can hang indefinitely under network issues, blocking the worker/request thread. Suggest `->timeout(30)`.
- **Full-table loads** — `Model::all()` on unbounded tables; use `->chunk()` or `->cursor()`.
- **Unnecessary re-fetch** — re-querying something already in scope.

---

### 10. Error Handling & Resilience

- External HTTP calls with no `$response->successful()` check or try/catch — 🟡 Warning.
- Swallowed exceptions: bare `catch (\Exception $e) {}` — 🔵 Suggestion.
- Missing fallback when a collection is empty but the next line assumes at least one element.

---

### 11. Migrations (`database/migrations/`)

- **Non-null column added to an existing table without a default value or a two-step migration** (add nullable → backfill → make non-null) — 🔴 Critical. This will lock the table on large datasets.
- **Model class referenced inside a migration** — 🔵 Suggestion. Prefer `DB::` or raw table names so the migration doesn't break if the Model is later renamed.
- **No `down()` method, or `down()` is empty** — 🔵 Suggestion. Rollback must be possible.
- **Missing index on a foreign key column** — 🔵 Suggestion.

```php
// BAD — will lock table during deploy on large datasets
Schema::table('users', function (Blueprint $table) {
    $table->string('phone')->after('email');  // non-null, no default
});

// GOOD — two-step: nullable first, then backfill, then constrain
$table->string('phone')->nullable()->after('email');
```

---

### 12. Vue / JavaScript Quality

- **Missing `:key` in `v-for`** — 🟡 Warning.
- **`:key="index"`** in a list that can reorder — 🔵 Suggestion.
- **`v-if` + `v-for` on the same element** — 🔵 Suggestion.
- **Direct Vuex state mutation** (`this.$store.state.x = y`) — 🟡 Warning.
- **`v-html` with unsanitised input** — 🔴 Critical.
- **`addEventListener` without `removeEventListener` in `beforeUnmount`** — 🔵 Suggestion.
- **Direct DOM manipulation** (`document.querySelector`) — 🔵 Suggestion; use `this.$refs`.
- **Axios without error handling** — 🟡 Warning.
- **Missing loading/error state** for async operations — 🔵 Suggestion.
- **Unscoped `<style>`** — 🔵 Suggestion.

---

### 13. Testing Signals

#### Untestable patterns (flag on the code, not on missing tests)

- `new ClassName()` inside business logic — 🔵 Suggestion (prevents mocking).
- `auth()`, `request()`, `session()` inside Services — 🟡 Warning (§1b).
- `$this->withoutExceptionHandling()` committed — 🟡 Warning (debugging aid must not be merged).

#### Test quality

- **Outbound HTTP in a test without `Http::fake()` or `fakeHttpResponse()`** — 🟡 Warning. Stray requests make tests flaky and environment-dependent.
- **Testing a private/protected method via reflection** — 🟡 Warning (test observable behaviour through the public API).
- **Test with no assertions** — 🔵 Suggestion (passes vacuously).
- **`assertStatus(200)` with no body assertion** — 🔵 Suggestion.
- **DB records created without `Tests\RefreshDatabase`** (use the project trait, not Laravel's built-in) — 🔵 Suggestion (risks test pollution).
- **`Mockery::mock()` used directly** instead of `mock(ClassName::class)` from `tests/Helpers.php` — 🔵 Suggestion (plain Mockery doesn't bind into the container).
- **Controller test that doesn't call `signIn()`** on a protected route — 🔵 Suggestion.
- **No unauthenticated path test** for a protected route — 🔵 Suggestion.

**Feature test vs Unit test:** Feature tests when the path touches HTTP, database, or external services. Unit tests for pure logic in a Service, DTO, or utility. A test that should be a Feature test written as a Unit test with a mocked repository may mask a real query bug.

---

### 14. API Design

- `POST` creating a resource returning `200` instead of `201` — 🔵 Suggestion.
- Collection endpoint with no pagination on an unbounded table — 🟡 Warning.
- API Resource exposing `created_at`, pivot columns, `password`, `remember_token`, or internal IDs — 🟡 Warning.
- Inconsistent response envelope shape — 🔵 Suggestion.

---

### 15. Blade views (`resources/views/`)

Views are presentation only. Anything that queries data, decides business rules, or runs PHP belongs in a controller, service, or view-composer.

#### 15a. No business logic in views

- Direct Eloquent queries (`User::find(...)`, `$x->orders()->count()`) inside Blade — 🟡 Warning. Pass the data from the controller / view-composer.
- `@php ... @endphp` blocks — 🟡 Warning. Almost always a smell; lift it out.
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
- `href="{{ $url }}"` or `src="{{ $url }}"` where the value is a user-supplied URL — 🟡 Warning. `{{ }}` escapes HTML but `javascript:foo()` still executes. Validate the scheme or whitelist URLs.
- Inline JS event handlers carrying user data (`onclick="doThing('{{ $msg }}')"`) — 🟡 Warning. Use unobtrusive JS or pass via a data attribute with `@json($msg)`.
- `style="{{ $userValue }}"` — 🔵 Suggestion. Style injection can leak data (`background-image: url(...)`) or break layout.

#### 15d. CSRF on state-changing forms

`<form method="POST" …>` (including spoofed `PUT`/`PATCH`/`DELETE` via `@method`) without `@csrf` — 🟡 Warning. The middleware will reject it at runtime; this is a bug-in-waiting.

#### 15e. Auth / Request / DB facades in views

`request()`, `auth()->user()`, `DB::`, raw query builders called directly from Blade — 🔵 Suggestion. Pass through the controller or a view-composer for testability and to keep layering clean.

`@auth` / `@guest` / `auth()->check()` for conditional rendering are documented patterns and fine.

#### 15f. Localisation

If the project uses `__()` / `trans()` elsewhere, hardcoded user-facing strings in new Blade content — 🔵 Suggestion. Apply only when the surrounding codebase is already localised.

#### 15g. Component extraction

A single Blade file over ~200 lines, or a `@foreach` body of complex markup over ~25 lines — 🔵 Suggestion. Extract a Blade component (`<x-…>`) or partial via `@include`.

#### 15h. Dynamic `@include` paths

`@include($var)` where `$var` could be influenced by request input — 🔴 Critical. Path-traversal / arbitrary view rendering risk.

---

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

**Unix mode:**
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

**Windows mode** (pipe a here-string into the `.ps1`):
```powershell
@'
[
  {
    "path": "app/Http/Controllers/UserController.php",
    "line": 22,
    "body": "🔴 **Critical** — ...\n\n### 1. The problem\n...",
    "dim": "3b",
    "severity": "critical"
  }
]
'@ | pwsh .claude/skills/code-reviewer/scripts/post_review.ps1
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
- **`post_review.sh`** — posts the compiled review as inline Bitbucket PR comments. Reads JSON from stdin. Requires `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` env vars.
- **`check_replies.py`** — prints a JSON array of open findings whose thread ends with an unanswered developer reply (see Step 0.7). Empty `[]` when nothing awaits a response.
- **`post_reply.py --parent-id=<ID>`** — posts a threaded reply (body on stdin) under a PR comment and tags it with a hidden `ai-review:reply` marker so the bot won't answer its own reply.
- **`setup_target.sh --branch=<name>|--pr=<N>`** — fetches a branch and creates a detached git worktree for reviewing without checkout. Writes `.ai-review/target.json` inside the worktree. Prints the worktree path to stdout.
- **`cleanup_target.sh <worktree-path>`** — removes a worktree created by `setup_target.sh`.

---

## Reference material

- `references/laravel_review_guide.md` — Laravel-specific patterns, anti-patterns, correctness traps
- `references/vue_review_guide.md` — Vue 3 / Vuex 4 patterns and component quality checks
- `references/coding_standards.md` — PSR-12, naming conventions, method length limits
- `references/common_antipatterns.md` — copy-paste reference for the most common violations
- `references/code_review_checklist.md` — quick checklist for every diff
