# Code Review Checklist

Rules from `.coderabbit.yaml` take precedence over everything here.
See `laravel_review_guide.md` for Laravel / PHP patterns.
See `vue_review_guide.md` for Vue / Vuex / JS patterns.

## Quick checklist — apply to every diff

### Global (all PHP files)
- [ ] No `dd()`, `dump()`, `die()` in committed code
- [ ] No `error_log()`, `var_dump()`, `print_r()`, `echo` for logging — use `Log::`
- [ ] No `$_SERVER`, `$_ENV`, `$_GET`, `$_POST`, `$_REQUEST` superglobals
- [ ] No hardcoded credentials or API keys
- [ ] `declare(strict_types=1)` on all new files under `app/`
- [ ] Every method: typed parameters AND return type
- [ ] Class properties typed (exempt: `$fillable`, `$casts`, `$guarded`, `$with`)

### Architecture & Layering
- [ ] Controller type-hints a FormRequest (no inline `$request->validate()`)
- [ ] Controller calls Service for write operations — no direct Eloquent
- [ ] Controller→Repository direct calls are reads only (not writes)
- [ ] Controller returns an API Resource — no `->toArray()` / `response()->json($model)`
- [ ] Controller has no business logic; method ≤ 40 lines; ≤ 5 constructor deps
- [ ] Service is HTTP-agnostic — no `Request`, `Auth::`, `auth()`, `redirect()`, `response()`, `session()`
- [ ] Service delegates DB work to a Repository — no direct Eloquent
- [ ] Service accepts typed DTOs at layer boundaries — not raw `array $data`
- [ ] Repository returns typed objects (`Model`, `Collection`, `?Model`)
- [ ] Repository has no business logic, no HTTP concerns
- [ ] DTO (app/Data/) is pure value container — no side effects, readonly properties
- [ ] Console Command `handle()` delegates to Service/Repository — no Eloquent/business logic

### FormRequests
- [ ] `rules()` is not empty
- [ ] Business logic absent from `rules()` / `authorize()`
- [ ] File/image fields have type allow-list (`mimes:` or `mimetypes:`) AND `max:`

### API Resources
- [ ] No DB queries or Service calls inside `toArray()`
- [ ] `$this->whenLoaded('relation')` used for related model fields

### Models
- [ ] No business logic or side effects in Model methods
- [ ] No HTTP concerns (`Request`, `Auth::`) in Model
- [ ] No `$guarded = []` without explicit `$fillable`
- [ ] Relationship methods have no eager-loading constraints (belongs in Repository)

### Enums
- [ ] No business logic beyond label/color/helper methods

### Security
- [ ] Authorization via Policy/Gate — no `if ($user->role === ...)` checks
- [ ] `FormRequest::authorize()` checks ownership or capability — not just `return true`
- [ ] No `fill/update/create` with `$request->all()` (mass assignment)
- [ ] No `whereRaw/DB::statement` with string interpolation (SQL injection)
- [ ] No `{!! $var !!}` on user-supplied content (XSS in Blade)
- [ ] File upload: `mimes:`/`mimetypes:` AND `max:` on file fields
- [ ] Resource owns the object it fetches — IDOR check
- [ ] No `env()` calls outside `config/` files

### Data Integrity
- [ ] Multi-write paths wrapped in `DB::transaction()`
- [ ] No check-then-act (`exists()` + `create()` → use `firstOrCreate`)

### Performance
- [ ] No Eloquent / relationship access inside loops (N+1)
- [ ] No `->load()` inside loops — lift above the loop
- [ ] `Http::` calls chain `->timeout(N)` — suggest `->timeout(30)`
- [ ] `->exists()` / `->count()` used instead of `->get()` + isEmpty / count

### Migrations
- [ ] Non-null column on existing table has a default or uses two-step migration
- [ ] No Model class references — use `DB::` or raw table names
- [ ] `down()` method implemented (not empty)
- [ ] Foreign key columns have an index

### Vue
- [ ] Every `v-for` has `:key` bound to a stable ID (not index)
- [ ] `v-if` and `v-for` not on the same element
- [ ] `addEventListener` has paired `removeEventListener` in `beforeUnmount`
- [ ] No direct Vuex state mutation (`$store.state.x = y`)
- [ ] Async store actions have try/catch

### Tests & Testability
- [ ] No `withoutExceptionHandling()` committed
- [ ] No outbound `Http::` without `Http::fake()` or `fakeHttpResponse()`
- [ ] No testing private/protected methods via reflection
- [ ] Test has at least one assertion beyond `assertStatus`
- [ ] DB records created using `Tests\RefreshDatabase` (not Laravel's built-in)
- [ ] `mock(ClassName::class)` from `tests/Helpers.php` — not `Mockery::mock()`
- [ ] Protected routes test the unauthenticated path
- [ ] Controller tests call `signIn()` before authenticated requests
