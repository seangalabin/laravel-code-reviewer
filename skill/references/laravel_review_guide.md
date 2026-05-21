# Laravel Review Guide

Patterns, anti-patterns, and correctness traps specific to this Laravel 10 / PHP 8.3 monolith. Secondary to `.coderabbit.yaml` — use this to fill gaps the yaml doesn't cover.

---

## Correctness traps

### Null-safe chaining
`$model->relation->attribute` will throw if `relation` is null. Use `$model->relation?->attribute` or guard with a null check. Common in Controllers when a lookup can return null — `firstOrFail()` is often the right call when null means "bad request."

### `firstOrCreate` vs `exists() + create()`
A separate existence check followed by a create is a race condition — two concurrent requests can both pass the check and both insert. Use `firstOrCreate()` or `updateOrCreate()` which are internally atomic (MySQL `INSERT IGNORE` under the hood).

### `->get()` followed by `->isEmpty()`
`->get()` fetches all rows; then you check if there are any. If you only need to know *whether* rows exist, use `->exists()`. If you only need the count, use `->count()`. Both hit the DB once and avoid materialising a collection.

### `$collection->count()` vs `->count()` on the query builder
If a collection is already fetched, `$collection->count()` is a PHP operation — no DB hit. `Model::where(...)->count()` is a DB query. Don't issue a second DB query to count something you already loaded.

### Eager loading before loops
Before iterating a collection and touching a relation, confirm the outer query calls `->with('relation')`. Reading `$item->relation` inside a loop without eager loading issues one query per iteration.

### `->load()` belongs outside loops
`$item->load('relation')` inside a loop = N queries. Load on the collection before iteration: `$collection->load('relation')` (one query for all items).

### `DB::transaction()` for multi-write paths
Any code path that issues two or more write queries (create + update, delete + insert, etc.) must be wrapped in `DB::transaction(fn() => ...)`. If the second write fails without a transaction, data is left inconsistent.

---

## Security

### Mass assignment
`$model->fill($request->all())` or `$model->update($request->all())` fills every request field into the model, including fields the user shouldn't control (e.g., `is_admin`, `role`, `balance`). Always pass a keyed array of explicitly allowed fields, or use a FormRequest with `safe()->only([...])`.

`$guarded = []` on a Model with no `$fillable` is the same risk — any column becomes fillable.

### SQL injection in raw queries
`->whereRaw("name = '$name'")` is injectable. Always use bound parameters: `->whereRaw('name = ?', [$name])` or `->whereRaw('name = :name', ['name' => $name])`.

### Insecure direct object reference
`Order::find($request->order_id)` in a controller without verifying `$order->user_id === auth()->id()` (or equivalent policy check) lets any authenticated user read/modify any order. Use `auth()->user()->orders()->findOrFail($id)` to scope the query, or check via a Policy.

### File upload security
A FormRequest rule of just `'file'` or `'image'` without `mimes:`/`mimetypes:` and `max:` is incomplete:
- `mimes:` / `mimetypes:` prevents disguised executables (`.php` renamed to `.jpg`)
- `max:` (in kilobytes) prevents DoS via large uploads

Both are required. Example: `'photo' => 'required|image|mimes:jpeg,png,webp|max:5120'`

### Sensitive data in API Resources
`toArray()` returning `$this->resource->toArray()` (the raw model) or exposing `password`, `remember_token`, `api_token`, pivot columns, or internal IDs leaks data. Explicitly list what fields each Resource exposes.

### `env()` in application code
`env('SOME_KEY')` returns `null` when the config is cached (`php artisan config:cache`), which is the norm in production. Always define a config key in `config/something.php` and call `config('something.key')` in application code.

---

## Performance

### N+1 — the patterns to spot

```php
// BAD — one query per iteration
foreach ($agents as $agent) {
    echo $agent->office->name;   // lazy-loads office each iteration
}

// GOOD — one query for all
$agents = Agent::with('office')->get();

// BAD — query inside loop body
foreach ($propertyIds as $id) {
    $assets = Asset::where('property_id', $id)->get();
}

// GOOD — batch load, then group
$assets = Asset::whereIn('property_id', $propertyIds)->get()->groupBy('property_id');
```

### `Http::` timeout
Every external HTTP call must chain `->timeout(N)` (seconds). Queue workers and web requests share the same PHP process pool — a hung request blocks a slot indefinitely.

```php
Http::timeout(30)->get($url);
```

### Chunking large datasets
`Model::all()` on a table with millions of rows loads everything into memory. For bulk operations use `->chunk(500, fn($batch) => ...)` or `->cursor()` (lazy evaluation).

---

## Code structure

### FormRequests must validate
`rules()` returning `[]` means any input is accepted. Every FormRequest must declare at minimum what fields are required and their types.

### Services must not know about HTTP
A Service that type-hints `Request`, calls `auth()`, or uses `redirect()`/`response()` cannot be used outside an HTTP context (jobs, commands, tests). Pass plain values or Data objects.

### Repository return types
Methods returning `null` when no record is found should declare `?Model` return type. Methods returning collections should declare `Collection`. Avoid returning plain `array` — callers get typed objects they can call methods on.

### Logging
Use the Laravel logging stack, not PHP primitives:
- `Log::info('msg', ['context' => $data])` — structured, level-aware, configurable per environment
- `error_log(...)` / `echo` — goes to PHP error log or stdout, not Laravel's channels

---

## Testing

### Pest 2 conventions in this repo
- Test files live in `tests/Feature/` only — no unit tests
- Test file name must match the class under test 1:1 (enforced by ArchitectureTest)
- `signIn(User|UserType)` — authenticate before hitting a route that requires auth
- `mock(ClassName::class)` — always use the helper from `tests/Helpers.php`, not `Mockery::mock()` directly
- `fakeHttpResponse(url, body, status)` — stub outbound HTTP; `Http::preventStrayRequests()` is enabled globally for Controller tests

### Meaningful assertions
`assertStatus(200)` alone tells you the route exists, not that it works. Assert the response structure:
```php
$response->assertStatus(200)
         ->assertJsonFragment(['name' => $agent->name])
         ->assertJsonMissing(['password']);
```

### Unauthenticated path
Every controller test should include an unauthenticated case: `$this->getJson('/route')->assertStatus(401)` (or 403). If a route is public, that's intentional — document it with a comment in the test.
