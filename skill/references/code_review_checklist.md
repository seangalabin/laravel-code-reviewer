# Code Review Checklist

See `laravel_review_guide.md` for Laravel / PHP patterns.
See `vue_review_guide.md` for Vue / Vuex / JS patterns.

## Quick checklist — apply to every diff

### Correctness
- [ ] No null dereference on potentially-null return values
- [ ] No race condition (separate exists-check + create → use firstOrCreate)
- [ ] No wrong HTTP status code in a JSON response
- [ ] Return type matches all code paths in the method signature

### Security
- [ ] No whereRaw/DB::statement with string interpolation
- [ ] No fill/update with $request->all() (mass assignment)
- [ ] No {!! $var !!} on user-supplied content (XSS)
- [ ] No v-html on user-supplied content (XSS)
- [ ] File upload FormRequest rules include mimes: and max:
- [ ] Resource owns the object it fetches (IDOR check)

### Data integrity
- [ ] Multi-write paths wrapped in DB::transaction()
- [ ] No check-then-act without locking

### Performance
- [ ] No Eloquent / relationship access inside loops (N+1)
- [ ] No ->load() inside loops — lift above the loop
- [ ] Http:: calls chain ->timeout(N)
- [ ] ->exists() / ->count() used instead of ->get() + isEmpty / count

### Vue
- [ ] Every v-for has :key bound to a stable ID (not index)
- [ ] v-if and v-for not on the same element
- [ ] addEventListener has paired removeEventListener in beforeUnmount
- [ ] No direct Vuex state mutation ($store.state.x = y)
- [ ] Async store actions have try/catch

### Tests
- [ ] Test has at least one assertion beyond assertStatus
- [ ] Unauthenticated path tested
- [ ] No withoutExceptionHandling() committed
