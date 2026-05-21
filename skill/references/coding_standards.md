# Coding Standards

House style for this Laravel 10 / Vue 3 codebase. Pint enforces PHP formatting automatically — this file covers the things Pint doesn't: naming, structure, and intent.

---

## PHP

### Naming
- Classes: `PascalCase` — `AgentRepository`, `CreateOrderService`
- Methods and variables: `camelCase` — `getActiveAgents()`, `$propertyIds`
- Constants and enum cases: `SCREAMING_SNAKE_CASE` or `PascalCase` for PHP 8.1+ enums
- Blade views: `kebab-case.blade.php` — `agent-profile.blade.php`
- Database columns: `snake_case` — `created_at`, `user_id`

### Method length
- Controller methods: target ≤ 20 lines. At 40+ lines, extract to a Service.
- Service methods: target ≤ 30 lines. Extract private helpers for distinct steps.
- Repository methods: as short as the query demands — no business logic.

### Return types — always declare
Every method must declare a return type. For PHP 8.3:
- `void` — no return value
- `never` — always throws or exits
- `?Type` — nullable
- `Collection` — Eloquent collections (import `Illuminate\Support\Collection`)
- `BelongsTo`, `HasMany`, `MorphMany`, etc. — relationship methods on Models
- `mixed` is acceptable as a deliberate choice, not a placeholder

### `declare(strict_types=1)`
All new files under `app/` must have `declare(strict_types=1)` as the first statement after `<?php`. Prevents silent type coercion bugs in PHP 8.3.

### Error handling
- Use `firstOrFail()` (throws `ModelNotFoundException` → 404) rather than `find()` + manual null check when a missing record is a client error.
- Wrap outbound HTTP calls in try/catch and check `$response->successful()`.
- Use `Log::error()` with context array for unexpected exceptions, not `report()` alone.

### Eloquent scopes
Repeated `->where('status', 'active')->whereNull('archived_at')` chains belong in a local scope on the Model:
```php
public function scopeActive(Builder $query): Builder {
    return $query->where('status', 'active')->whereNull('archived_at');
}
// Usage: Agent::active()->get()
```

---

## Vue / JavaScript

### Naming
- Component files: `PascalCase.vue` — `AgentProfile.vue`, `OrderList.vue`
- Component names in template: `<AgentProfile>` (PascalCase) or `<agent-profile>` (kebab) — be consistent within a file
- Props: `camelCase` in JS, `kebab-case` in templates — Vue handles the conversion
- Events emitted: `kebab-case` — `@update:modelValue`, `@close-modal`
- Vuex store modules: `camelCase` — `agentProfile`, `orderList`

### Component structure order
Follow the Options API ordering for consistency:
1. `name`
2. `components`
3. `props`
4. `emits`
5. `data()`
6. `computed`
7. `watch`
8. `lifecycle hooks` (mounted, beforeUnmount, etc.)
9. `methods`

### Props
- Always declare type and `required` or `default`.
- Objects and arrays must use a `default: () => ({})` / `default: () => []` factory function — plain `default: {}` is shared across instances.

### Methods
- Async methods that call the API should handle loading state and errors (see `vue_review_guide.md`).
- Avoid methods longer than 30 lines — extract helpers or move logic to a Vuex action.

### Template readability
- Avoid ternary expressions longer than one line in templates — compute in a `computed` instead.
- Self-close empty elements: `<MyComponent />` not `<MyComponent></MyComponent>`.
- One attribute per line when a tag has more than 2 attributes.

### Axios
- Use the shared axios instance (already configured with the CSRF token and base URL).
- Check `response.data.data` for paginated Laravel Resource responses; `response.data` for single resources — the envelope depends on what the API Resource returns.
