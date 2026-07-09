# Engineering standards — {COMPANY}

> Drop this file in your Laravel project root as `CLAUDE.md`. Every Claude Code session working in this repo reads it, and so do the `/code-reviewer` and `/code-fixer` skills (as project overrides). **Write code that already follows these rules** — it should pass review the first time. For anything that only changes review *behaviour* — disabling a check, changing a severity, or adding a project-specific/framework rule — use `.claude/code-review-rules.md` instead.

We are a Laravel + (Vue/React) team. The base branch is `develop`. CI runs **Pint** (formatting) and **Pest** (tests) before code review — so don't hand-fix formatting; focus on the rules below.

---

## 1. Architecture — Controller → Service → Repository → Model

This layering is **non-negotiable**. Each layer has one job.

**Controllers** are HTTP adapters only. A controller method should type-hint a `FormRequest`, call **one** Service method (or a Repository for a simple read), and return an API Resource. Controllers must **not**:
- contain business logic (multi-step workflows, business rules, domain calculations),
- issue Eloquent queries or call Model static methods directly,
- validate inline with `$request->validate(...)` — use a `FormRequest`,
- do authorization inline (`if ($user->role === 'admin')`) — use a Policy/Gate,
- return `$model->toArray()` / `response()->json($model)` — use an API Resource.

**Services** own all business logic. They accept plain values or DTOs (never a `Request`), delegate every query to a Repository, and stay HTTP-agnostic — no `auth()`, `request()`, `session()`, `redirect()`, or `response()` inside a Service.

**Repositories** own all Eloquent/query logic. They return typed Eloquent objects (`Model`, `Collection`, `?Model`), hold no business logic and no HTTP concerns. **One Repository per aggregate root** — a child model (`OrderItem`) lives in the parent's Repository (`OrderRepository`), not its own.

**Models** hold relationships, casts, and query scopes — not business logic, not HTTP.

**Enums** are value descriptors (labels, colours, allowed transitions) — no DB queries, HTTP/`Auth`, or event/job dispatch on an enum; that belongs in a Service.

**Data across boundaries:** data crossing into and out of a **Service** is a typed **DTO** (`app/Data/`), not a raw `array`. Repositories return Eloquent objects, which flow up to the Service. **Console commands:** `handle()` is a thin CLI adapter — delegate to a Service/Repository; no business logic or queries inline.

---

## 2. Code style

- `declare(strict_types=1);` at the top of every PHP file in `app/`.
- **Full type declarations** — every parameter and return type (`__construct` has none). Type class **properties** too, except Eloquent's framework arrays (`$fillable`, `$casts`, `$guarded`, …).
- **Naming:** `PascalCase` classes, `camelCase` methods/variables, `SCREAMING_SNAKE_CASE` constants, singular Model names. Names must be descriptive — no `$d`, `$tmp`, `process()`, `getData()`.
- **Methods are verb phrases that tell the truth.** `calculateTotal()`, not `total()`. A `get*`/`find*` method must not secretly mutate, persist, or dispatch — the name must match the behaviour.
- **Readability:** positive `if` conditions (not negated with an `else`), guard clauses over deep nesting, no redundant `else` after `return`, no nested ternaries, no boolean flag arguments, ≤5 parameters (group into a DTO). Test emptiness with `empty()` / `->isEmpty()`, not `count() > 0`.
- **No magic numbers/strings** — HTTP codes, role/status strings, and business limits belong in a constant, enum, or config.

## 3. Comments — only where the code can't explain itself

Write self-documenting code; reach for a clearer name or an extracted method before a comment. A comment explains **why** (a non-obvious constraint, a workaround, a regulatory reason), never restates **what** the code already says.

- ❌ Don't narrate the code (`$i++; // increment i`), and don't leave commented-out code — Git history keeps it.
- ✅ Do add a short *why* comment where logic is genuinely subtle.

## 4. Security (non-negotiable)

- **Authorization** goes through Policies/Gates (`$this->authorize()`, `authorizeResource()`, `@can`, `->can:` middleware) — never inline role checks. If a `{Model}Policy` exists, use it.
- **No mass assignment** — never `Model::create($request->all())`; pass `$request->safe()->only([...])`.
- **No raw-SQL interpolation** — bind values with `?` in `whereRaw`/`DB::statement`/etc.; allow-list column/direction identifiers (they can't be bound).
- **Scope resources to the user** — fetch owned records via the relationship (`auth()->user()->orders()->find($id)`), not a bare `Order::find($request->id)` (IDOR).
- **Validate file uploads** — a type allow-list (`mimes:`/`File::types()`) **and** a size cap.
- **Never hardcode secrets** — API keys, passwords, tokens live in `.env`, read via `config()`. Never `env()` outside a config file.
- **No debug/superglobal leftovers** — no `dd()`/`dump()`/`die()`, no `var_dump()`/`print_r()`/`error_log()`/`echo` for logging (use `Log::info()`/`error()`/`debug()`), and no PHP superglobals (`$_GET`/`$_POST`/`$_REQUEST`/`$_SERVER`/`$_ENV`) — read input via `request()`/`config()`.

## 5. Laravel & Eloquent

- **Avoid N+1** — eager-load relations (`with()`); never re-fetch a related model by FK (`User::find($fk)`) when a relationship exists.
- **API Resources** for every JSON response returning a model/collection; never expose `password`/`remember_token` or internal columns. Inside a Resource's `toArray()`, transform already-loaded data only — no queries or Service calls — and wrap not-guaranteed-loaded relations in `$this->whenLoaded('relation')`.
- **GET is side-effect free** — never persist/update/delete/dispatch behind a GET route; use POST/PUT/PATCH/DELETE. A create action returns `201`, not `200`.
- **Queue slow or blocking work** (email, PDF, external calls, loops of HTTP) via Jobs; queue Mailables/Notifications with `ShouldQueue`.
- **Transactions & races** — wrap multi-write paths that must succeed or fail together in `DB::transaction()`; for get-or-create use `firstOrCreate()`/`updateOrCreate()`, not `exists()`-then-`create()` (races/double-inserts).
- **External calls** — check the result (`$response->successful()` or try/catch), set `->timeout(N)` on every outbound `Http::`, and handle a null/malformed body before indexing into it. Never swallow an exception in an empty `catch` — log, rethrow, or handle.
- **Large datasets** — `chunkById()` (not `chunk()`) on mutable tables; keep queued jobs **idempotent** (they re-run); assume many workers run at once (atomic ops / `lockForUpdate()`).

## 6. Correctness

- **Guard nullable relations** before dereferencing (`$order->customer?->name`, or an early return) — an unguarded chain on a request path is a 500.
- **Strict comparisons** on ids/tokens/hashes — `===` and `in_array($x, $a, true)`, never loose `==`.
- **Exhaustive `match`/`switch`** over an enum, or give it a `default` — a new case otherwise throws.
- **Money** is integer cents or a decimal type, never a float.

## 7. Migrations

- Never add a **non-null column to an existing table without a default** — go nullable → backfill → constrain (otherwise it locks/fails the deploy on existing rows).
- Always write a working `down()`; index foreign-key columns.
- Treat `dropColumn` / `renameColumn` / type-narrowing as **destructive** — confirm the data is expendable and sequence the deploy.

## 8. Blade views (presentation only)

- Escape output with `{{ }}`. Use `{!! !!}` **only** for trusted, non-user HTML — raw-echoing user input is XSS.
- `@csrf` on every state-changing form (`POST`/`PUT`/`PATCH`/`DELETE` via `@method`).
- No Eloquent queries or business logic in a view or `@php` block — pass data from the controller/view-composer.
- Eager-load any relation accessed inside a `@foreach` (N+1). Never `@include()` a request-influenced path.

## 9. Front-end frameworks (Vue / React / …)

Follow the idioms of whatever framework the file uses. Universally: no unsanitised HTML injection (`v-html` / `dangerouslySetInnerHTML` / `innerHTML`) with user input; clean up listeners/subscriptions/timers on teardown; handle async error/loading states; keep list keys stable; don't mutate props or state directly.

## 10. Testing

- **Feature tests** for anything touching HTTP, the database, or external services; **unit tests** for pure logic (Services, DTOs, utilities).
- Tests make **real assertions** — no assertion-free or tautological tests; fake outbound HTTP (`Http::fake()`); test the public API, not private methods via reflection.

---

## For Claude Code sessions working in this repo

When you're unsure whether something belongs in a Controller, Service, or Repository, default to the layering in §1. If you make a deliberate trade-off that bends a rule, say why in the PR description or a card comment — the reviewer reads that and won't flag an explained, justified choice (but a real security/correctness bug still stands).
