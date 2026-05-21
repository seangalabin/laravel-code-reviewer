# Vue Review Guide

Patterns, anti-patterns, and correctness traps for the Vue 3 / Vuex 4 / Vue Router 4 frontend in this repo. Components use the Options API. Bootstrap Vue Next is auto-resolved — no explicit import needed.

---

## Template correctness

### `v-for` must have `:key`
Every `v-for` requires a `:key` bound to a **stable unique identifier** — the record's database ID, not the loop index.

```html
<!-- BAD — no key -->
<div v-for="item in items">

<!-- BAD — index as key; incorrect patches when items reorder or are removed -->
<div v-for="(item, index) in items" :key="index">

<!-- GOOD -->
<div v-for="item in items" :key="item.id">
```

Without a key, Vue reuses existing DOM nodes in document order, which produces incorrect output when the list reorders, filters, or has items added/removed mid-list.

### `v-if` and `v-for` on the same element
`v-for` takes priority — Vue iterates the full list, *then* evaluates `v-if` on each item. This means the condition runs per-item even if most items should be excluded. Move the `v-if` to a wrapper element, or pre-filter the list in a `computed`.

```html
<!-- BAD — iterates all items, then hides most -->
<li v-for="item in items" v-if="item.active" :key="item.id">

<!-- GOOD — filter first -->
<li v-for="item in activeItems" :key="item.id">
```
```js
computed: {
    activeItems() { return this.items.filter(i => i.active); }
}
```

### `v-html` and XSS
`v-html` injects raw HTML into the DOM — any `<script>` tag or event handler in the value runs. Safe only when:
1. The content originates from a trusted internal source (e.g., markdown rendered server-side by a known library), **and**
2. It is never formed from user-supplied strings.

If there is any doubt, use a sanitiser (DOMPurify) before assignment, or avoid `v-html` entirely.

### `<style scoped>`
Every `<style>` block must be `<style scoped>` unless intentionally global. Without `scoped`, CSS selectors leak into the global stylesheet and break unrelated components. Global styles belong in `resources/css/` or a dedicated top-level `<style>` in `App.vue`.

---

## Reactivity

### Direct array mutation
In Vue 3 (Proxy-based), direct index assignment (`this.items[0] = newItem`) *is* reactive — but `this.items.length = 0` is not. Prefer splice, concat, or filter/map returns to maintain predictable reactivity:
```js
// GOOD — replaces array reactively
this.items = this.items.filter(i => i.id !== id);
// GOOD — appends reactively
this.items = [...this.items, newItem];
```

### Direct Vuex state mutation
`this.$store.state.module.prop = value` bypasses Vuex mutations — Vue DevTools won't track the change, time-travel debugging breaks, and strict mode throws.

Always go through a mutation: `this.$store.commit('module/SET_PROP', value)` or an action: `this.$store.dispatch('module/updateProp', value)`.

---

## Component lifecycle and memory leaks

### `addEventListener` must have a paired `removeEventListener`
Listeners attached in `mounted()` or `created()` persist after the component is destroyed unless explicitly removed in `beforeUnmount()` (Vue 3) / `beforeDestroy()` (Vue 2). Failure to clean up:
- Causes memory leaks in long-lived SPAs
- Fires handlers on destroyed component instances (can cause "cannot set property on undefined" errors)
- Accumulates duplicate listeners on each re-mount

```js
mounted() {
    this._resizeHandler = () => this.onResize();
    window.addEventListener('resize', this._resizeHandler);
},
beforeUnmount() {
    window.removeEventListener('resize', this._resizeHandler);
}
```

### Direct DOM manipulation
`document.querySelector()`, `document.getElementById()`, `document.getElementsBy*()` in a component bypass Vue's reactivity and lifecycle management. Use `this.$refs.name` instead:

```html
<input ref="search" />
```
```js
this.$refs.search.focus();
```

---

## State management (Vuex)

### Async actions need error handling
An action that `await`s an axios call without `try/catch` will silently reject the returned Promise, leaving the UI in the loading state indefinitely.

```js
// BAD
async fetchOrders({ commit }) {
    const { data } = await axios.get('/api/orders');
    commit('SET_ORDERS', data.data);
}

// GOOD
async fetchOrders({ commit }) {
    try {
        const { data } = await axios.get('/api/orders');
        commit('SET_ORDERS', data.data);
    } catch (error) {
        commit('SET_ERROR', error.response?.data?.message ?? 'Request failed');
    }
}
```

### Loading and error state
Any action that makes a network request should track loading state so the UI can show a spinner and disable the submit button. Missing loading state allows double-submissions and leaves users without feedback when requests are slow.

```js
// In store
SET_LOADING(state, val) { state.loading = val; }

async saveOrder({ commit }, payload) {
    commit('SET_LOADING', true);
    try { ... } finally { commit('SET_LOADING', false); }
}
```

### Store module structure for this repo
Modules live in `resources/js/store/modules/` (31 modules). Each module uses namespacing. When reading context for a Vue component change, check the module it dispatches to — mis-matched mutation names fail silently.

---

## Axios and HTTP

### Every axios call needs error handling
`axios.get(url)` returns a Promise. Without `.catch()` or `try/catch` around `await`, a non-2xx response or network error produces an unhandled rejection.

### Response shape consistency
This repo's API responses use `{ data: {...} }` or `{ data: [...] }` envelopes via Laravel API Resources. A component that reads `response.data` instead of `response.data.data` gets the axios wrapper, not the Laravel resource. Check which shape the corresponding API Resource returns.

---

## Performance

### `v-show` vs `v-if`
- `v-if` fully mounts/unmounts the component on every toggle — use when the element is rarely shown, or when mounting is expensive.
- `v-show` toggles `display: none` — keep the DOM node alive. Use for elements that toggle frequently (tabs, toggleable panels, search filters).

### `computed` for derived data
Data that is derived from other reactive data should be a `computed` property, not recalculated in the template on every render. A `computed` result is cached until its dependencies change.

```js
// BAD — recalculated on every render
// template: {{ items.filter(i => i.active).length }}

// GOOD — cached
computed: {
    activeCount() { return this.items.filter(i => i.active).length; }
}
```

### Deep watchers on large objects
`watch: { bigObject: { deep: true, handler() {} } }` traverses every nested property on every change. Prefer watching a specific nested path (`'bigObject.specificProp'`) or using `computed` to derive the value you actually care about.

---

## Props and component contracts

### Prop validation
Props should declare their type and whether they're required:
```js
props: {
    agent: { type: Object, required: true },
    pageSize: { type: Number, default: 20 },
}
```
Missing prop types mean Vue cannot warn during development when a parent passes the wrong type.

### Emitting events
Declare emitted events with `emits: ['update:modelValue', 'close']` (Vue 3). Undeclared emits work but generate warnings and make the component's contract invisible to consumers.
