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

`$guarded = []` without an explicit `$fillable` list: 🔵 Suggestion — flag, suggest adding `$fillable`.

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

Inside an API Resource's `toArray()`: no DB queries, no Service calls — 🟡 Warning (Resources transform already-loaded data only). Use `$this->whenLoaded('relation')` for related models — omitting it causes N+1 queries when the relation was not eager-loaded — 🔵 Suggestion.

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

#### 4g. `DB::transaction()` for multi-write paths

Any code path that issues two or more write queries must be wrapped in `DB::transaction()`. A missing transaction on a Service multi-write path is 🔵 Suggestion:

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
- `$guarded = []` without `$fillable` — 🔵 Suggestion.

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

- Multiple Eloquent writes without `DB::transaction()` — 🔵 Suggestion.
- Check-then-act race conditions: `->exists()` + `->create()` → use `firstOrCreate()`.
- Missing `->lockForUpdate()` on rows read-then-modified concurrently.

---

### 9. Performance

- **N+1** — §4b. Always 🟡 Warning.
- **`->get()` then `->isEmpty()`** — use `->exists()` or `->count()` on the query builder.
- **`Http::` without `->timeout(N)`** — 🔵 Suggestion. Suggest `->timeout(30)`.
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

