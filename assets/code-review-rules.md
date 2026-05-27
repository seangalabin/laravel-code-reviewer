# Company review rules

Custom, company-specific rules for `/code-reviewer` and `/code-fixer`. These are
read **in addition to** the skill's built-in review lens and take **precedence**
over it — when a rule here conflicts with a built-in one, the rule here wins.

This file is committed and shared with your team. The skill installer creates it
once and never overwrites it, so edit it freely.

## How to write a rule

- Use the same severity markers as the built-in lens: 🔴 Critical, 🟡 Warning, 🔵 Suggestion.
- Reference the actual helper, class, or pattern in your codebase — be concrete.
- A `BAD` / `GOOD` example pair makes the rule unambiguous for the reviewer.
- To **disable** a built-in dimension, say so explicitly, e.g.
  "Disable dimension 6 (Enums) — we don't use this convention."

---

## Exception logging — use `report()`

Exceptions that are caught and handled (not rethrown), or that wrap-and-throw,
must be sent to the logging platform via our `report()` helper. `report()` is the
single path to the configured logging channel, so the error stays visible in
monitoring instead of vanishing.

- A `catch` block that handles an exception locally without calling `report($e)` — 🟡 Warning. The error disappears from monitoring.
- An exception sent through the `Log` facade (`Log::error($e)`, `Log::warning($e)`, …) instead of `report($e)` — 🔵 Suggestion. The `Log` facade is avoided here because those entries are hard to trace; use `report()` so it reaches the configured channel.
- Before throwing a new/wrapped exception that swallows the original cause, `report()` the original — 🔵 Suggestion.

```php
// BAD — caught and silently dropped; monitoring never sees it
try {
    $this->gateway->charge($order);
} catch (PaymentException $e) {
    return false;
}

// BAD — Log facade entry is hard to trace and skips the configured channel
} catch (PaymentException $e) {
    Log::error($e->getMessage());
    return false;
}

// GOOD — reported to the configured channel, then handled
} catch (PaymentException $e) {
    report($e);
    return false;
}
```

Rethrowing untouched (`throw $e;`) or letting it bubble to the global handler is
fine — the handler reports it. The rule targets exceptions that are **caught and
not rethrown**.

---

<!-- Add more company rules below. -->
