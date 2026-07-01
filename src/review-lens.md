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

#### 2n. Descriptive, meaningful names — 🔵 Suggestion

§2d governs *casing*; this rule governs whether the name actually says what the thing is. A name that is correctly `camelCase` but opaque (`$tmp`, `$d`, `handle2()`) is worth a nudge. It's 🔵 — an opaque-but-honest name is a readability suggestion; a name that actively *misleads* about behaviour is the 🟡 case in §2p. Flag identifiers — variables, properties, parameters, methods — whose name does not convey their role:

- **Cryptic / single-letter variables** outside the idioms below — `$d`, `$x`, `$a2`, `$str`, `$obj`.
- **Vague placeholder names** that carry no meaning — `$data`, `$data2`, `$tmp`, `$temp`, `$val`, `$arr`, `$res`, `$info`, `$thing`, `$stuff`, `$foo`. (`$result` is fine when it genuinely *is* the result of the method.) **Judge by role, not spelling:** a short-lived local whose meaning is obvious from the adjacent line — e.g. `$data` passed straight into `Model::create($data)` — is acceptable; don't flag a name the surrounding context already explains.
- **Unclear abbreviations** that aren't well-known — `$usrRepo` → `$userRepository`, `$calcAmt` → `$calculatedAmount`, `$ctr` → `$counter`.
- **Vague method names** that don't state what they do — `process()`, `doStuff()`, `doIt()`, `manage()`, `getData()`, `run2()`. Name the action and its subject — `calculateInvoiceTotal()`, `markOrderShipped()`.

```php
// BAD
public function process($d): array {
    $tmp = [];
    foreach ($d as $x) {
        $tmp[] = $x->total * 1.1;
    }
    return $tmp;
}

// GOOD
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

A comment should explain **why** (a non-obvious constraint, a workaround, a business/regulatory reason), not **what** the code already says. The first fix for unclear code is a clearer name or an extracted method — not a comment. Flag three things:

- **Redundant / obvious comments** that merely restate the code — `$i++; // increment i`, `// loop over users`, `// return the result`. Delete them; they add noise and drift out of date.
- **Commented-out code** left in the diff — delete it. Git history preserves anything you might want back; dead code in the file is just clutter.
- **A genuinely hard-to-follow block with no explanatory comment** — when logic is unavoidably dense (a tricky algorithm, a non-obvious edge-case guard, a deliberate deviation from the obvious approach), a short *why* comment is warranted. Suggest adding one, or refactoring so it isn't needed.

```php
// BAD — restates the code
// increment the counter by one
$counter++;

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

#### 2p. Method names are verb phrases — 🔵 Suggestion

A method *does* something, so its name should start with a verb: `calculateTotal()`, `sendInvoice()`, `markAsPaid()`, `syncTags()` — not a bare noun like `total()`, `invoiceData()`, or `tags()` (for a method that performs work). Flag a method whose name is a noun/adjective with no verb as 🔵 Suggestion, suggesting a verb-led rename.

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

🔴 Critical:

```php
// BAD — injectable
->whereRaw("name = '$name'")
DB::statement("DELETE FROM users WHERE id = $id")

// GOOD
->whereRaw('name = ?', [$name])
```

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
- Magic numbers/strings that belong in `config/` or an enum — see §2i.

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

**Exempt — do NOT flag:**
- Obvious dummy/test values in tests, factories, and seeders (`'password'`, `bcrypt('password')`, `'secret'`, `'test-token'`).
- Placeholders and examples (`.env.example`, `'your-api-key-here'`, `'xxxxx'`).
- **Public** keys / publishable keys (`pk_live_…`, public certificates) — not secret by design.
- Non-secret config defaults (timeouts, URLs without credentials).
- **High-entropy values that aren't credentials** — SHA/MD5 hashes, checksums, idempotency or cache keys, migration/UUID literals, encoded data payloads — even when the variable name matches `*key*` / `*token*` / `*auth*`. A matching name alone is not enough; flag only when the value is actually used to authenticate or sign.

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

- Null dereferences: `$model->relation->attribute` where `relation` could be `null` — 🔴 on a request path (uncaught 500), 🟡 if guarded or non-fatal.
- Off-by-one, wrong conditional, inverted boolean — 🟡 (🔴 if it causes data loss or corruption).
- Check-then-act races (`exists()` + `create()`) — see §8 (canonical).
- A value the **removed** lines null-checked, bounds-checked, or early-returned on is now used unchecked in the **added** lines — 🔴 if it can crash or corrupt, else 🟡. (Anchor to the removed guard; don't speculate about guards you can't see.)
- Semantically wrong HTTP status — `200` on a not-found or error path — 🟡. (The `201`-vs-`200`-on-create convention lives in §14.)
- Return type mismatches across code paths — 🟡.

---

### 8. Data Integrity

- Multiple Eloquent writes without `DB::transaction()` — see §4g (canonical rule, 🟡 Warning).
- Check-then-act race conditions (canonical): `->exists()` + `->create()` → use `firstOrCreate()` / `updateOrCreate()` — 🟡 Warning.
- Missing `->lockForUpdate()` on rows read-then-modified — 🟡 Warning.

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

A single Blade file over ~200 lines, or a `@foreach` body of complex markup over ~25 lines — 🔵 Suggestion. Extract a Blade component (`<x-…>`) or partial via `@include`.

#### 15h. Dynamic `@include` paths

`@include($var)` where `$var` could be influenced by request input — 🔴 Critical. Path-traversal / arbitrary view rendering risk.

---

