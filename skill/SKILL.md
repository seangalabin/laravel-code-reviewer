---
name: code-reviewer
description: Diff-scoped code review for the current branch. Reviews ONLY the lines changed since the base branch (develop) — not entire files. Covers architecture & layering, PSR-12, security, Laravel best practices, testability, and Vue/JS quality.
---

# Code Reviewer

Reviews the **current branch's changes** against the base branch (`develop` for this repo). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## Step 0 — Load project rules (ALWAYS do this first)

Before reviewing a single line of code:

1. Check for `.coderabbit.yaml` in the project root:
   ```bash
   cat .coderabbit.yaml 2>/dev/null || echo "(no .coderabbit.yaml found)"
   ```
2. Check for `CLAUDE.md` in the project root and `.claude/` directory.
3. **Rules in `.coderabbit.yaml` take precedence over every rule in this skill.** Where `.coderabbit.yaml` overrides or extends a rule below, apply the `.coderabbit.yaml` version. Note any overrides in your review output.

For the HQ project specifically, the `.coderabbit.yaml` is at `C:\laragon\www\hq\.coderabbit.yaml` (WSL path: `/mnt/c/laragon/www/hq/.coderabbit.yaml`).

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

---

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

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter.

---

## Workflow

1. **Load project rules** (Step 0 above).
2. **Diff first.** Read every hunk. Do not start by reading whole files.
3. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — findings on those files are out of scope unless changed.
4. **Apply the full review lens** (all sections below) to everything in the diff.
5. **Compile findings** grouped by severity (see Output format).
6. **Post findings** as inline Bitbucket PR comments.

```bash
.claude/skills/code-reviewer/scripts/post_review.sh <<'FINDINGS'
[
  {
    "path": "app/Http/Controllers/UserController.php",
    "line": 22,
    "body": "🔴 **Critical** — `User::create($request->all())` — mass assignment with no field filtering..."
  }
]
FINDINGS
```

---

## Review lens

Work through these dimensions in order. Apply `.coderabbit.yaml` rules first; these dimensions extend them.

---

### 1. Architecture & Layering (first-class concern)

The repo enforces a **Controller → Service → Repository → Model** call graph.

**Permitted shortcuts (per `.coderabbit.yaml`):**
- Controller → Repository is acceptable for **read-only** lookups.
- Controller → Repository for **write** operations is 🟠 Major — writes must go through a Service to keep transactions and side-effects in one place.

Every violation of the layering rules below is at minimum 🟠 Major.

#### 1a. Controller responsibilities

Controllers are HTTP adapters only. They must:
- Receive a typed `FormRequest` (validation already done)
- Call one Service method (or a Repository for simple reads) with plain values or a DTO
- Return an API Resource or a paginated collection Resource

Controllers must NOT:
- Contain business logic (conditionals, calculations, multi-step workflows)
- Issue Eloquent queries or call Model static methods directly — 🟠 Major
- Call `$request->validate(...)` inline — use a `FormRequest` — 🟠 Major
- Contain `if ($user->role === ...)` or any manual authorization — use Policies/Gates — 🟠 Major
- Return `$model->toArray()`, `response()->json($model)`, or a raw array — use an API Resource — 🟠 Major
- Have a constructor injecting more than 5 dependencies — 🟡 Minor (God controller smell)

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

Controller method length: flag at **40+ lines** as 🟡 Minor (suggest extracting to Service).

#### 1b. Service responsibilities

Services own all business logic. They must:
- Accept plain values or typed DTOs — never a `Request` object — 🟠 Major
- Delegate all Eloquent/query work to a Repository — 🟠 Major
- Be HTTP-agnostic: no `auth()`, `Auth::`, `redirect()`, `response()`, `session()` — 🟠 Major
- Be injectable via the service container — `new ServiceClass()` inside another Service is 🟡 Minor

Service method length: flag at **30+ lines** as 🟡 Minor.

#### 1c. Repository responsibilities

Repositories own all Eloquent/query logic. They must:
- Return typed objects (`Model`, `Collection`, `?Model`) — returning a plain `array` is 🟡 Minor
- Contain no business logic, no HTTP concerns — 🟠 Major
- Use Eloquent scopes for reusable filter chains — a very long query chain where a named scope would help readability is 🔵 Suggestion
- Avoid eager-loading constraints inside relationship methods — those belong in the Repository query, not on the Model

#### 1d. DTOs for cross-layer data

Data passing **into** or **out of** a Service must use a typed DTO class, not a raw `array`. Flag any Service method signature that accepts `array $data` as 🟡 Minor.

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

Every Controller method that accepts user input must type-hint a dedicated `FormRequest` subclass. Inline `$request->validate([...])` in a Controller or Service is 🟠 Major. A `FormRequest` with an empty `rules()` method is also 🟠 Major.

#### 1f. Console Commands

`handle()` in a Console Command is a thin CLI adapter — it must delegate to a Service or Repository. Direct Eloquent queries or business logic inside `handle()` is 🟠 Major. Use `$this->info()` / `$this->error()` for output (not `echo`) — 🟡 Minor.

---

### 2. PSR-12 & Code Standards

#### 2a. `declare(strict_types=1)`

All new PHP files under `app/` must open with `declare(strict_types=1)` as the first statement after `<?php`. Flag as 🟡 Minor.

```php
<?php

declare(strict_types=1);

namespace App\Http\Controllers;
```

#### 2b. Type declarations — MUST FIX (🟠 Major)

Per `.coderabbit.yaml`: **every method signature must declare types for every parameter AND a return type.** This applies to public, protected, and private methods on classes, traits, and abstract classes alike. Both missing parameter types and missing return types are 🟠 Major.

- `void` — no return value
- `never` — always throws or exits
- `self` / `static` — fluent setters
- `?Type` — nullable; use instead of untyped nullable
- `mixed` — acceptable as a deliberate choice, not a placeholder
- Eloquent relation types: `BelongsTo`, `HasMany`, `MorphMany`, etc. on Model relationship methods

**Exemptions (per `.coderabbit.yaml`):**
- Closures passed to Pest's `it()`, `test()`, `describe()`, `beforeEach()` do not need return types.
- Magic methods (`__get`, `__set`, `__call`) follow PHP's required signature.

#### 2c. Property type declarations

Class properties under `app/` must be typed. 🟡 Minor.

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

Manual role/permission checks in Controllers or Services are 🟠 Major:

```php
// BAD
if (auth()->user()->role === 'admin') { ... }
if ($request->user()->is_admin) { ... }

// GOOD
$this->authorize('update', $user);
Gate::authorize('update-user', $user);
```

Every `FormRequest::authorize()` that unconditionally returns `true` without a comment explaining why (e.g., genuinely public endpoint) is 🟡 Minor.

#### 3b. Mass assignment

🟠 Major (downgraded from Critical per `.coderabbit.yaml` — `$guarded = []` without `$fillable` is a WARN):

```php
// BAD
User::create($request->all());
$user->update($request->all());
$user->fill($request->all())->save();

// GOOD
$user->update($request->safe()->only(['name', 'email', 'phone']));
```

`$guarded = []` without an explicit `$fillable` list: 🟡 Minor — flag, suggest adding `$fillable`.

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

🟠 Major — any controller that fetches a resource by ID without scoping to the authenticated user or checking a Policy:

```php
// BAD
$order = Order::findOrFail($request->order_id);

// GOOD
$order = auth()->user()->orders()->findOrFail($request->order_id);
```

#### 3e. File upload security

🟠 Major — a FormRequest that accepts file uploads without **both** a type allow-list and a size cap. Per `.coderabbit.yaml`, either `mimes:` or `mimetypes:` is acceptable (both sniff actual file contents):

```php
// BAD
'photo' => 'required|file'

// GOOD — either form is acceptable
'photo' => 'required|image|mimes:jpeg,png,webp|max:5120'
'photo' => 'required|image|mimetypes:image/jpeg,image/png|max:5120'
```

#### 3f. Sensitive data leaks

- `{!! $var !!}` in Blade or `v-html` in Vue where value could be user-supplied — 🔴 Critical.
- API Resources that return `password`, `remember_token`, `api_token`, or raw pivot data — 🟠 Major.
- `Log::info()` / `Log::error()` that logs a full request body, password, or token — 🟠 Major.

#### 3g. `env()` outside config files

🟠 Major — returns `null` when config is cached in production:

```php
// BAD
$key = env('STRIPE_SECRET');

// GOOD
$key = config('services.stripe.secret');
```

#### 3h. Global forbidden patterns (🟠 Major in all files)

Per `.coderabbit.yaml`:
- `dd()`, `dump()`, `die()` — forbidden in committed code.
- `error_log()`, `var_dump()`, `print_r()`, `echo` used for logging — use `Log::info()` / `Log::error()` / `Log::debug()`.
- `$_SERVER`, `$_ENV`, `$_GET`, `$_POST`, `$_REQUEST` — use Laravel helpers (`request()`, `config()`).
- Hardcoded credentials, API keys, or magic numbers that belong in `config/` or `.env`.

---

### 4. Laravel Best Practices

#### 4a. API Resources — no raw `toArray()` or model-to-JSON

Every JSON response must use a dedicated API Resource. Raw `->toArray()`, `response()->json($model)`, or `$model->toJson()` in a Controller are 🟠 Major:

```php
// BAD
return response()->json($user->toArray());

// GOOD
return new UserResource($user);
return UserResource::collection($users);
```

Inside an API Resource's `toArray()`: no DB queries, no Service calls — 🟠 Major (Resources transform already-loaded data only). Use `$this->whenLoaded('relation')` for related models — omitting it causes N+1 queries when the relation was not eager-loaded — 🟡 Minor.

FormRequest validation: flag raw string rules where a `Rule` object would be safer (e.g. `Rule::unique()`, `Rule::exists()`) — 🔵 Suggestion.

#### 4b. Eloquent N+1 queries

Any Eloquent query or relationship access inside a loop body without prior eager loading is 🟠 Major. `->load()` inside a loop is the same violation — lift it above the loop.

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

#### 4c. Eloquent scopes

Repeated query chains belong in a named local scope. Flag duplicated filter chains as 🔵 Suggestion.

#### 4d. Fillable / guarded hygiene

`$guarded = []` without an explicit `$fillable` — 🟡 Minor (flag, suggest `$fillable`).

#### 4e. Jobs, Events, Listeners, Observers — when to require them

Flag as 🟠 Major when inline Controller/Service code should be extracted:

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

`new ClassName()` inside a Controller, Service, or Repository where the class should be injected is 🟡 Minor. This includes `new OtherService()` inside a Service constructor body.

#### 4g. `DB::transaction()` for multi-write paths

Any code path that issues two or more write queries must be wrapped in `DB::transaction()`. A missing transaction on a Service multi-write path is 🟡 Minor (WARN per `.coderabbit.yaml`):

```php
// GOOD
DB::transaction(function () use ($data, $items) {
    $order = Order::create($data);
    $order->items()->createMany($items);
});
```

---

### 5. Models

- Complex business logic or side effects inside a Model method — 🟠 Major.
- HTTP concerns (`Request`, `response()`, `Auth` facade) inside a Model — 🟠 Major.
- A method that issues its own Eloquent query instead of defining a scope — 🟡 Minor.
- Relationship method that contains eager-loading constraints (belongs in the Repository query, not the Model) — 🟡 Minor.
- `$guarded = []` without `$fillable` — 🟡 Minor.

---

### 6. Enums (`app/Enums/`)

Business logic beyond label, color, or helper methods on the enum itself is 🟠 Major. Enums are value descriptors only.

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

- Multiple Eloquent writes without `DB::transaction()` — 🟡 Minor (WARN per `.coderabbit.yaml`).
- Check-then-act race conditions: `->exists()` + `->create()` → use `firstOrCreate()`.
- Missing `->lockForUpdate()` on rows read-then-modified concurrently.

---

### 9. Performance

- **N+1** — §4b. Always 🟠 Major.
- **`->get()` then `->isEmpty()`** — use `->exists()` or `->count()` on the query builder.
- **`Http::` without `->timeout(N)`** — 🟡 Minor (WARN per `.coderabbit.yaml`). Suggest `->timeout(30)`.
- **Full-table loads** — `Model::all()` on unbounded tables; use `->chunk()` or `->cursor()`.
- **Unnecessary re-fetch** — re-querying something already in scope.

---

### 10. Error Handling & Resilience

- External HTTP calls with no `$response->successful()` check or try/catch — 🟠 Major.
- Swallowed exceptions: bare `catch (\Exception $e) {}` — 🟡 Minor.
- Missing fallback when a collection is empty but the next line assumes at least one element.

---

### 11. Migrations (`database/migrations/`)

- **Non-null column added to an existing table without a default value or a two-step migration** (add nullable → backfill → make non-null) — 🔴 Critical. This will lock the table on large datasets.
- **Model class referenced inside a migration** — 🟡 Minor. Prefer `DB::` or raw table names so the migration doesn't break if the Model is later renamed.
- **No `down()` method, or `down()` is empty** — 🟡 Minor. Rollback must be possible.
- **Missing index on a foreign key column** — 🟡 Minor.

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

- **Missing `:key` in `v-for`** — 🟠 Major.
- **`:key="index"`** in a list that can reorder — 🟡 Minor.
- **`v-if` + `v-for` on the same element** — 🟡 Minor.
- **Direct Vuex state mutation** (`this.$store.state.x = y`) — 🟠 Major.
- **`v-html` with unsanitised input** — 🔴 Critical.
- **`addEventListener` without `removeEventListener` in `beforeUnmount`** — 🟡 Minor.
- **Direct DOM manipulation** (`document.querySelector`) — 🟡 Minor; use `this.$refs`.
- **Axios without error handling** — 🟠 Major.
- **Missing loading/error state** for async operations — 🟡 Minor.
- **Unscoped `<style>`** — 🟡 Minor.

---

### 13. Testing Signals

#### Untestable patterns (flag on the code, not on missing tests)

- `new ClassName()` inside business logic — 🟡 Minor (prevents mocking).
- `auth()`, `request()`, `session()` inside Services — 🟠 Major (§1b).
- `$this->withoutExceptionHandling()` committed — 🟠 Major (debugging aid must not be merged).

#### Test quality (per `.coderabbit.yaml`)

- **Outbound HTTP in a test without `Http::fake()` or `fakeHttpResponse()`** — 🟠 Major. `preventStrayRequests()` is enabled globally for `tests/Feature/Http/Controllers`, `tests/Feature/Mail`, and `tests/Feature/View/Components` via `tests/Pest.php`.
- **Testing a private/protected method via reflection** — 🟠 Major (test observable behaviour through the public API).
- **Test with no assertions** — 🟡 Minor (passes vacuously).
- **`assertStatus(200)` with no body assertion** — 🟡 Minor.
- **DB records created without `Tests\RefreshDatabase`** (use the project trait, not Laravel's built-in) — 🟡 Minor (risks test pollution).
- **`Mockery::mock()` used directly** instead of `mock(ClassName::class)` from `tests/Helpers.php` — 🟡 Minor (plain Mockery doesn't bind into the container).
- **Controller test that doesn't call `signIn()`** on a protected route — 🟡 Minor.
- **No unauthenticated path test** for a protected route — 🟡 Minor.

**Feature test vs Unit test:** Feature tests when the path touches HTTP, database, or external services. Unit tests for pure logic in a Service, DTO, or utility. A test that should be a Feature test written as a Unit test with a mocked repository may mask a real query bug.

---

### 14. API Design

- `POST` creating a resource returning `200` instead of `201` — 🟡 Minor.
- Collection endpoint with no pagination on an unbounded table — 🟠 Major.
- API Resource exposing `created_at`, pivot columns, `password`, `remember_token`, or internal IDs — 🟠 Major.
- Inconsistent response envelope shape — 🟡 Minor.

---

## Output format

### Severity buckets

| Emoji | Severity | Merge policy |
|---|---|---|
| 🔴 | **Critical** | Blocks merge immediately. Security vuln, data integrity break, auth bypass, exposed credentials, XSS, table-locking migration. |
| 🟠 | **Major** | Must fix before merge. Architecture violation, N+1, missing API Resource, business logic in Command, broken correctness, stray HTTP in test. |
| 🟡 | **Minor** | Should fix, doesn't block. PSR-12 drift, missing types, naming, untestable pattern, missing migration down(). |
| 🔵 | **Suggestion** | Consider. Refactor opportunity, scope extraction, Rule object over raw string, DRY improvement. |

### Finding format

Each finding must include all three parts:

```
🟠 **app/Http/Controllers/UserController.php:14** — Direct Eloquent in Controller

**Offending code:**
\`\`\`php
$user = User::where('email', $request->email)->first();
\`\`\`

**Why:** Controllers must not contain Eloquent queries. This couples the HTTP layer
to the database, prevents mocking in tests, and violates the Controller → Service
→ Repository contract.

**Fix:**
\`\`\`php
// In UserController — inject and delegate
$user = $this->userService->findByEmail($request->email);

// In UserService
public function findByEmail(string $email): ?User {
    return $this->users->findByEmail($email);
}

// In UserRepository
public function findByEmail(string $email): ?User {
    return User::where('email', $email)->first();
}
\`\`\`
```

### Scorecard (always include at end)

Grade each area A–F: **A** = no issues, **B** = Minor/Suggestion only, **C** = 1–2 Major, **D** = multiple Major or one Critical, **F** = multiple Critical or systemic violation.

```markdown
## Scorecard

| Concern | Grade | Summary |
|---------|-------|---------|
| Architecture Compliance | ? | |
| PSR-12 & Code Standards | ? | |
| Security | ? | |
| Testability | ? | |

**Verdict:** [safe to merge / not safe to merge as-is — N Critical, M Major]
```

---

## What not to do

- Don't open untouched files to look for new issues.
- Don't grade the whole architecture from a small change.
- Don't restate `.coderabbit.yaml` rules verbatim — CodeRabbit already does that on the PR.
- Don't flag issues caught by Pint or the Pest ArchitectureTest.
- Don't invent issues to fill buckets. An empty 🔴/🟠 list is a valid and welcome outcome.
- Don't run Pint, Pest, or ESLint — CI runs these before the card moves to code review.

---

## Scripts

- **`branch_summary.sh [base]`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py [--base REF] [--no-snippets]`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.
- **`post_review.sh`** — posts the compiled review as inline Bitbucket PR comments. Reads JSON from stdin. Requires `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` env vars.

---

## Reference material

- `references/laravel_review_guide.md` — Laravel-specific patterns, anti-patterns, correctness traps
- `references/vue_review_guide.md` — Vue 3 / Vuex 4 patterns and component quality checks
- `references/coding_standards.md` — PSR-12, naming conventions, method length limits
- `references/common_antipatterns.md` — copy-paste reference for the most common violations
- `references/code_review_checklist.md` — quick checklist for every diff
