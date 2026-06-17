---
name: code-fixer
description: Diff-scoped code review and interactive fix applicator for the current branch. Reviews ONLY lines changed since develop, then walks you through applying fixes locally. No Bitbucket posting.
---

# Code Fixer

Reviews the **current branch's changes** against the base branch (`develop` for this repo). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## OS detection (once, before Step -1)

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

## Step -1 — Version check (always first, before anything else)

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

## Step 0 — Check for project-specific overrides (optional)

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

## Step 0.1 — Load card context (recommended)

Before analyzing, fetch the linked issue-tracker card so the lens evaluates your branch against the actual ask — not just whether the code is clean. You're auditing your own work; the card tells you whether you finished it.

1. **Find the ticket reference.** Look, in order, for a pattern like `[A-Z][A-Z0-9_]*-\d+` (Atlassian project key format — e.g. `B20-11233`, `PROJ-42`):
   - Current branch name (e.g. `feature/B20-11233-add-stats-...`)
   - Recent commit subjects on the branch (`git log --format=%s origin/develop..HEAD`)

2. **Fetch the card.** Use the first available source — never block the run on this:
   - **Atlassian MCP** tools (`mcp__claude_ai_Atlassian__getJiraIssue`, `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql`) when configured. Preferred.
   - **Branch name** — last resort; gives only the slugified card title.

3. **Read these fields when available:** Title, Description, Acceptance criteria, Type (bug / feature / refactor).

4. **Use this as reference context for Step 1, not as a new scope.** The Scope rule below is unchanged — you still review only what the branch touched. The card informs **judgment**:
   - Does the branch address the stated problem?
   - Does it satisfy the explicit acceptance criteria? (Missing requirements → 🟡 Warning.)

4a. **File relatedness check — every changed file should plausibly belong to this task.** List the changed files (`git diff --name-only origin/develop...HEAD`) and, for each, ask: *does this file's change serve the card's stated goal?* Flag any file with **no plausible connection** as a 🟡 Warning, phrased to confirm — not accuse:

   > 🟡 `{path}` doesn't appear related to {TICKET} ({one-line task summary}). Confirm it belongs on this branch, or move it out — unrelated changes ride in unreviewed and muddy the diff.

   **Use judgement — a file that legitimately *supports* the task is related**, even if the card doesn't name it: the implementation files, the layers they call through, the view/component that surfaces the change, any config/migration they require, and the matching tests all count. Only flag files whose change has **no believable link** to the stated work — a stray formatting sweep, a leftover debug statement, a merge artifact, or an edit in a feature area the task never mentions. Skip this check when no card context was obtained (step 5).

5. **No ticket detected** → print `No ticket reference detected — auditing branch against develop only.` and continue.

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

Print `🔍 Refreshing origin/develop...` then run:

```bash
git fetch origin develop
```

The review is diffed against `origin/develop`. A stale remote-tracking ref means the diff base is wrong.

- Success → print `  ✓ origin/develop up to date.` and continue.
- Failure (offline, no remote, etc.) → print `  ↷ Couldn't refresh develop — reviewing against your local copy.` and continue. A missing fetch is not fatal; the local `origin/develop` is still usable.

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
git diff origin/develop...HEAD    # source of truth for scope
```

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter.

---

## Workflow

### Narration — show the run, don't run it silently

Before invoking each script in Steps -1 → 0.1 and the scoping scripts in Step 1, print a one-line header naming the step in plain language (e.g. `Step -1 — Checking skill version`). After each script returns, **always relay the script's own progress lines** (the `🔍 / ✓ / ↷ / ⚠️` messages it prints to stdout/stderr) — never swallow them. End each step with a one-line outcome summary so the developer can follow the run. Quiet success is a regression — every step must produce at least one visible line.

### Step 1 — Analyze

1. **Load project rules** (Step 0 above).
2. **Refuse if on a protected branch.** Run `git branch --show-current`. If it returns `main`, `master`, or `develop`, stop: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`
3. **Diff first.** Run the scoping scripts and read every hunk. Do not start by reading whole files.
4. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — findings on those files are out of scope unless changed.
5. **Apply the full review lens** (all sections below) to everything in the diff.
6. **Compile all findings** grouped by severity (🔴 Critical → 🟡 Warning → 🔵 Suggestion). Do not modify any files yet.

Print a brief summary once analysis is done:

> Found **{N} issues** ({X} critical, {Y} warnings, {Z} suggestions). Starting fix loop.

### Step 2 — Pre-flight checks

Run these before touching any file:

1. Refuse if branch is `main`, `master`, or `develop` (already caught in Step 1).
2. Run `git status --short`. If the working tree has uncommitted changes, ask:
   > Working tree has uncommitted changes. Apply fixes anyway? [y/N]
   Default is **no** — stop unless the user explicitly types `y`.
3. Count files affected by the planned fixes. If more than 20, list the files and ask:
   > {N} files would be modified. This is above the 20-file safety limit. Proceed anyway? [y/N]
   Default is **no** — stop unless the user explicitly confirms.

### Step 3 — Fix loop

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

### Step 4 — Learning summary (private — author only, never posted)

After the fix loop ends, generate a short learning summary for the developer who ran the skill. This is a **private artefact** — it exists to help the author stay sharp while the bot does the review work. It must **never** appear on Bitbucket, never be folded into a posted comment, never be attached to any external surface — this is `code-fixer`, which is local-only by design, and the summary stays local too.

**Output exactly two places:**
1. Print to the terminal so the author sees it at end of run.
2. Append to `.ai-review/learning-log.md` (the directory is gitignored — verify before writing). Create the file if missing; never overwrite a previous entry.

**Template (same shape as `/code-reviewer`'s Step 3 — keep these in lockstep):**

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

#### 2e. Positive conditionals (if/else only)

When an `if` has an `else` branch, the `if` should test the **positive/truthy** case, not a negation — the reader shouldn't have to mentally invert the condition and then read the `else` as "the normal case". Flag `if (<negated>) { … } else { … }` as 🔵 Suggestion: swap the branches and drop the negation.

```php
// BAD — negated if with an else
if (! $user->isActive()) {
    return $this->reject();
} else {
    return $this->grant();
}

// GOOD — positive if, branches swapped
if ($user->isActive()) {
    return $this->grant();
} else {
    return $this->reject();
}
```

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

A boolean literal passed at a call site (`$service->generate($data, true, false)`) is unreadable — the reader can't tell what `true` means without opening the signature. 🔵 Suggestion. Prefer two intention-revealing methods, a named enum, or (last resort) a named argument (`generate($data, force: true)`). Judgement rule — a single, obvious boolean on a well-named method is acceptable.

#### 2k. Long parameter lists

A method/constructor with **more than 5** parameters — 🔵 Suggestion. Group related params into a DTO (see §1d) or a value object. (Distinct from §1a's controller-constructor DI cap, which is about *dependency* count.)

#### 2l. Double negatives

A negatively-named variable then tested negatively — `$notReady` with `if (! $notReady)`, `$isInvalid` with `! $isInvalid` — forces a double mental inversion. 🔵 Suggestion. Rename to the positive (`$ready`, `$isValid`) and flip the uses.

#### 2m. `count()` for emptiness checks

`count($x) > 0` / `count($x) === 0` to test emptiness — 🔵 Suggestion. Use `! empty($x)` / `empty($x)` for arrays, or `$collection->isNotEmpty()` / `->isEmpty()` for Eloquent collections — clearer intent and (for collections) avoids materialising a count.

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
- Don't restate `.coderabbit.yaml` rules verbatim if the project uses CodeRabbit — it already does that on the PR.
- Don't flag issues caught by Pint or the Pest ArchitectureTest as *findings* — they're CI's job. (You still **run** Pint/Pest/lint to verify each applied fix, per Step 3.4 — that's verification, not a finding.)
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

- **`branch_summary`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`pint_changed`** — run Pint against changed PHP files. Check-only by default; the fixer uses check-only (never auto-stages).
- **`pest_for_changed`** — run only the Pest tests that map to changed files (`app/Foo/Bar.php` → `tests/Feature/Foo/BarTest.php`).
