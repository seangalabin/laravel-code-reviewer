---
name: code-reviewer
description: Diff-scoped code review for the current branch. Reviews ONLY the lines changed since the base branch (develop) — not entire files. Use when reviewing pull requests, providing feedback on uncommitted changes, or auditing a branch before merge.
---

# Code Reviewer

Reviews the **current branch's changes** against the base branch (`develop` for this repo, per `CLAUDE.md`). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

## Scope rule (read this first)

**Review only what the branch changed.** That means:

- Added or modified lines in the diff — fair game, always.
- Deleted lines — fair game if the deletion introduces a regression or removes a guard.
- Pre-existing lines **inside a touched hunk** — fair game when the surrounding change makes them newly relevant.
- Pre-existing lines **outside any hunk, in a file the branch did not touch** — out of scope. Do not surface.
- Files the branch did not touch — out of scope. Do not open them looking for issues.

Reading surrounding context (the rest of the changed file, the called Repository, the consuming Vue store) is encouraged for *understanding* the change. Findings are still bounded by the rule above.

When a pre-existing issue is in a touched hunk, label it `(pre-existing, but touched)`.

## Scoping the review

Run these up-front to anchor the review:

```bash
.claude/skills/code-reviewer/scripts/branch_summary.sh    # what changed: file counts, commits, base ref
.claude/skills/code-reviewer/scripts/scan_diff.py         # pre-pass: pattern matches for mechanical red flags
```

Then read the full diff:

```bash
git diff origin/develop...HEAD    # source of truth for scope
```

Use `origin/develop...HEAD` (three dots) — everything the branch added since forking from develop.

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter. Its job is to surface mechanical pattern matches so nothing slips by.

## Workflow

1. **Diff first.** Read every hunk. Do not start by reading whole files.
2. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — but findings on those files are out of scope unless they were changed.
3. **Apply the full review lens** (see below) to everything in the diff.
4. **Compile findings as a tight report** — file:line anchors, severity buckets, concrete suggestions (see Output format).
5. **Post findings as inline comments on the Bitbucket PR.**

```bash
.claude/skills/code-reviewer/scripts/post_review.sh <<'FINDINGS'
[
  {
    "path": "app/Http/Controllers/OrderController.php",
    "line": 88,
    "body": "**MUST FIX** — `Order::where('user_id', $id)->get()` inside `foreach` loop — N+1. Batch-load before the loop with `Order::whereIn('user_id', $ids)->get()->groupBy('user_id')`."
  },
  {
    "path": "resources/js/components/OrderList.vue",
    "line": 43,
    "body": "**WARN** — `v-for` over `orders` with no `:key`. Add `:key=\"order.id\"` to prevent incorrect DOM reuse during re-renders."
  },
  {
    "body": "**Review summary**\n\n2 MUST FIX, 1 WARN.\n\n**Verdict: not safe to merge as-is.** ..."
  }
]
FINDINGS
```

Use the line number from the diff (`+` side) for each finding. The script finds the open PR for the current branch automatically. If posting fails (no open PR, missing credentials), show the review inline.

## Review lens — what to look for in every hunk

Work through these dimensions in order. Apply `.coderabbit.yaml` and `CLAUDE.md` rules first; these dimensions extend them.

### 1. Correctness

- Will this code do what the author intends? Trace the happy path and the failure path.
- Null dereferences: accessing a property or method on a value that could be `null` without a null-safe operator (`?->`) or guard.
- Off-by-one, wrong conditional, inverted boolean.
- Missing guard after a refactor — something that was previously protected upstream is now exposed.
- Incorrect status codes in JSON responses (`200` for a created resource, `200` for a not-found, etc.).
- Return type mismatches: method declared to return `Collection` but a code path returns `null` or `array`.

### 2. Security

- **SQL injection**: `whereRaw()`/`DB::statement()` with string interpolation or concatenation, not bound parameters.
- **Mass assignment**: `$guarded = []` on a Model with no explicit `$fillable`; `fill($request->all())` or `update($request->all())` without filtering.
- **XSS**: `{!! $var !!}` in Blade, `v-html` in Vue — flag unless the value is sanitised before assignment.
- **Auth bypass**: `authorize()` missing or returning `true` unconditionally in a FormRequest; broken Gate/Policy logic that grants access to wrong roles.
- **File upload risk**: a FormRequest rule that includes `file` or `image` without both `mimes:`/`mimetypes:` and `max:` — type allow-list prevents disguised executables, size cap prevents DoS.
- **Sensitive data leak**: logging a password, token, or full request body with user credentials; returning sensitive model fields in an API Resource without `$this->when()` guards.
- **Insecure direct object reference**: a controller that fetches a resource by ID from the request without verifying the authenticated user owns it.

### 3. Data integrity

- Multiple Eloquent write operations (create + update, delete + insert, etc.) in the same code path without `DB::transaction()` — any failure between writes leaves data inconsistent.
- Check-then-act race conditions: separate `->exists()` check followed by `->create()` instead of `firstOrCreate()` or `->lockForUpdate()`.
- Missing `->lockForUpdate()` on rows that are read-then-modified in a concurrent context (e.g., decrementing stock, incrementing a counter).

### 4. Performance

- **N+1 queries**: any Eloquent query, Repository call, or relationship access (`$model->relation`) inside a `foreach`/`for`/`while` loop body. The fix is always: eager-load before the loop with `->with('relation')` / `->with(['rel.nested'])`, or batch-load with `whereIn` then group the results.
- **`->load()` inside a loop**: `$item->load('relation')` in a loop body issues one query per iteration — lift it above the loop onto the collection: `$collection->load('relation')`.
- **Unnecessary re-fetch**: querying for something already in scope (e.g., re-fetching `$user` that was already passed in, or calling `->count()` on a collection that was already fetched — use `$collection->count()` not a new query).
- **Missing `->with()` before consuming a relation**: accessing `$model->relation` anywhere without confirming the relation was eager-loaded in the calling query. Check the Repository or Controller that built the collection.
- **`Http::` without timeout**: any `Http::get()`, `Http::post()`, etc. without a chained `->timeout(N)` — hangs indefinitely and blocks queue workers or web requests.
- **Full-table loads when existence suffices**: `->get()` followed by `->isEmpty()` or `count($results) > 0` — use `->exists()` or `->count()` directly on the query builder.

### 5. Error handling & resilience

- External HTTP calls (`Http::get`, Guzzle, curl) with no error handling — what happens on a 4xx/5xx or network timeout? At minimum, check `$response->successful()` or wrap in try/catch.
- Missing fallback when a collection is empty but the next line assumes at least one element.
- Swallowed exceptions: bare `catch (\Exception $e) {}` or `catch` that only `Log::error`s but continues as if nothing happened when it should re-throw or return an error response.

### 6. Vue / JavaScript quality

- **Missing `:key` in `v-for`**: every `v-for` must have `:key` bound to a stable unique identifier (the record's database ID, not the array index — index keys cause incorrect DOM reuse when items reorder or are removed).
- **Index as `:key`**: `:key="index"` in a list that can reorder or have items removed — causes Vue to patch the wrong component instances.
- **`v-if` + `v-for` on the same element**: `v-for` always takes priority, making `v-if` iterate before filtering — move `v-if` to a wrapper element or use a `computed` filtered list.
- **Direct Vuex state mutation**: `this.$store.state.module.prop = value` — always go through a `commit('mutation')` so Vue DevTools tracks the change and state stays auditable.
- **`v-html` with unsanitised input**: XSS risk. Acceptable only when the content comes from a trusted internal source. If it's user-generated, it must be sanitised (DOMPurify or equivalent) before assignment.
- **Event listener leak**: `addEventListener` in `mounted()`/`created()` without a paired `removeEventListener` in `beforeUnmount()`/`destroyed()` — causes memory leaks and duplicate handlers on navigation.
- **Direct DOM manipulation**: `document.querySelector()`/`document.getElementById()` in a Vue component — use `this.$refs.name` instead so Vue controls the lifecycle.
- **Axios without error handling**: an `axios.get/post/...` call with no `.catch()` or `try/catch` around `await` — unhandled rejection crashes the action silently.
- **Missing loading/error state**: an async operation (API call, store dispatch) that can fail but has no loading indicator or error feedback path — users see no signal when the request hangs or fails.
- **Unscoped `<style>`**: a `<style>` block without `scoped` — CSS leaks globally and can break unrelated components.

### 7. Test quality

- **No assertions**: a test that exercises code but asserts nothing — passes vacuously.
- **Status-code-only test**: `assertStatus(200)` with no assertion on the response body — doesn't verify the feature works, only that the route exists.
- **Missing edge cases**: a new feature test that only covers the happy path — flag if obvious failure paths (unauthenticated, invalid input, empty collection, non-existent record) are untested.
- **`$this->withoutExceptionHandling()` committed**: debugging aid, must not be merged.
- **Wrong mock scope**: `Mockery::mock()` used directly instead of `mock(ClassName::class)` from `tests/Helpers.php` — the helper binds into the container; plain Mockery does not.

### 8. API design

- A `POST` that creates a resource but returns `200` instead of `201`.
- A collection endpoint with no pagination that could return thousands of rows.
- An API Resource that exposes internal fields (`created_at`, pivot columns, internal IDs) that clients don't need.
- Inconsistent response envelope: some endpoints return `{data: [...]}`, others return a bare array — pick one shape per endpoint type.

## Output format

Group findings under two buckets:

- **MUST FIX** — blocks merge: security issue, data-integrity risk, N+1 in a non-trivial loop, broken correctness, `.coderabbit.yaml` MUST FIX violation.
- **WARN** — should be addressed but doesn't block: missing edge-case test, style drift, minor perf, pre-existing-but-touched issues.

Each finding:
- File:line anchor matching a changed line in the diff.
- One sentence stating the problem.
- One sentence stating the fix (or a short code snippet).
- `(pre-existing, but touched)` tag when applicable.

End with a **one-paragraph summary**: what the branch does, how many MUST FIX / WARN, and the merge verdict. No gate tables — CI handles Pint, Pest, and ESLint before the card reaches code review.

## What not to do

- Don't open untouched files to look for new issues.
- Don't grade the whole architecture from a small change.
- Don't restate `.coderabbit.yaml` rules verbatim — CodeRabbit already does that in the PR. Add the human-tier review on top: intent, correctness, edge cases.
- Don't invent issues to fill buckets. An empty MUST FIX list is a valid and welcome outcome.
- Don't run Pint, Pest, or ESLint — the CI pipeline runs these before the card moves to code review.

## Scripts

- **`branch_summary.sh [base]`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py [--base REF] [--no-snippets]`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`post_review.sh`** — posts the compiled review as inline comments on the open Bitbucket PR. Reads JSON from stdin. Requires `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` env vars (set in `.claude/settings.local.json`).

## Reference material

- `references/laravel_review_guide.md` — Laravel-specific patterns, anti-patterns, and correctness traps
- `references/vue_review_guide.md` — Vue 3 / Vuex 4 patterns and component quality checks
