# Common Antipatterns

Patterns that appear frequently in PRs and cause bugs, performance issues, or security problems. Each entry has the bad pattern, why it's wrong, and the fix.

---

## PHP / Laravel

### N+1 — query inside a loop
```php
// BAD
foreach ($properties as $property) {
    $assets = Asset::where('property_id', $property->id)->get(); // 1 query per iteration
}

// GOOD
$assets = Asset::whereIn('property_id', $propertyIds)->get()->groupBy('property_id');
foreach ($properties as $property) {
    $propertyAssets = $assets->get($property->id, collect());
}
```

### ->load() inside a loop
```php
// BAD
foreach ($orders as $order) {
    $order->load('items');  // 1 query per order
}

// GOOD
$orders->load('items');  // 1 query for all orders, called before the loop
```

### Race condition: exists + create
```php
// BAD — two requests can both pass the check and both insert
if (!Agent::where('email', $email)->exists()) {
    Agent::create(['email' => $email]);
}

// GOOD — atomic
Agent::firstOrCreate(['email' => $email], $otherFields);
```

### Multi-write without transaction
```php
// BAD — if the second write fails, the first is committed with no rollback
$order = Order::create($data);
$order->items()->createMany($items);

// GOOD
DB::transaction(function () use ($data, $items) {
    $order = Order::create($data);
    $order->items()->createMany($items);
});
```

### Mass assignment via $request->all()
```php
// BAD — user can inject any field (is_admin, balance, role, etc.)
$model->update($request->all());
$model->fill($request->all())->save();

// GOOD
$model->update($request->safe()->only(['name', 'email', 'phone']));
// or define $fillable on the Model and use validated():
$model->update($request->validated());
```

### env() outside config files
```php
// BAD — returns null when config is cached in production
$key = env('STRIPE_SECRET');

// GOOD — define in config/services.php, call via config()
$key = config('services.stripe.secret');
```

### Http:: without timeout
```php
// BAD — hangs indefinitely, blocks a queue worker slot
$response = Http::get($url);

// GOOD
$response = Http::timeout(30)->get($url);
```

### Direct Eloquent in a Controller
```php
// BAD — violates Repository layer
class OrderController {
    public function index() {
        $orders = Order::where('user_id', auth()->id())->get();
    }
}

// GOOD
class OrderController {
    public function index(OrderRepository $repo) {
        $orders = $repo->getForUser(auth()->user());
    }
}
```

### Inline validation in a Controller
```php
// BAD
public function store(Request $request) {
    $request->validate(['name' => 'required']);
}

// GOOD — move to a FormRequest
public function store(StoreOrderRequest $request) {
    // validation already passed
}
```

### authorize() always returns true
```php
// BAD — any user can do anything
public function authorize(): bool { return true; }

// GOOD
public function authorize(): bool {
    return $this->user()->can('create', Order::class);
}
```

### Logging via echo / error_log
```php
// BAD — goes to PHP error log or stdout, not configurable
echo "processing order $id";
error_log("failed: " . $e->getMessage());

// GOOD — structured, level-aware, routes through Laravel's log channels
Log::info('Processing order', ['order_id' => $id]);
Log::error('Order processing failed', ['order_id' => $id, 'error' => $e->getMessage()]);
```

---

## Vue / JavaScript

### Missing :key in v-for
```html
<!-- BAD — Vue reuses DOM nodes in document order -->
<tr v-for="order in orders">

<!-- GOOD -->
<tr v-for="order in orders" :key="order.id">
```

### Index as :key
```html
<!-- BAD — when items reorder, Vue patches the wrong instances -->
<li v-for="(item, index) in items" :key="index">

<!-- GOOD — use a stable database ID -->
<li v-for="item in items" :key="item.id">
```

### v-if + v-for on same element
```html
<!-- BAD — v-for runs first, then v-if filters per item — wasteful -->
<li v-for="item in items" v-if="item.active" :key="item.id">

<!-- GOOD — filter in a computed -->
<li v-for="item in activeItems" :key="item.id">
```

### Direct Vuex state mutation
```js
// BAD — bypasses DevTools tracking, breaks strict mode
this.$store.state.orders.list = [];

// GOOD
this.$store.commit('orders/SET_LIST', []);
```

### addEventListener without cleanup
```js
// BAD — handler persists after component is destroyed; accumulates on re-mount
mounted() {
    window.addEventListener('resize', this.onResize);
}

// GOOD
mounted() {
    this._onResize = () => this.onResize();
    window.addEventListener('resize', this._onResize);
},
beforeUnmount() {
    window.removeEventListener('resize', this._onResize);
}
```

### Async action without error handling
```js
// BAD — unhandled rejection on non-2xx; UI stays in loading state
async fetchAgent({ commit }, id) {
    const { data } = await axios.get(`/api/agents/${id}`);
    commit('SET_AGENT', data.data);
}

// GOOD
async fetchAgent({ commit }, id) {
    try {
        const { data } = await axios.get(`/api/agents/${id}`);
        commit('SET_AGENT', data.data);
    } catch (error) {
        commit('SET_ERROR', error.response?.data?.message ?? 'Failed to load agent');
    } finally {
        commit('SET_LOADING', false);
    }
}
```

### v-html with user content
```html
<!-- BAD — XSS if $description is user-supplied -->
<div v-html="agent.description"></div>

<!-- GOOD — only when content is from a trusted internal source -->
<!-- or sanitise first: <div v-html="sanitise(agent.description)"> -->
```

### Direct DOM manipulation
```js
// BAD — bypasses Vue's lifecycle; breaks SSR; ref is lost after re-render
document.querySelector('#search-input').focus();

// GOOD
this.$refs.searchInput.focus();
```
