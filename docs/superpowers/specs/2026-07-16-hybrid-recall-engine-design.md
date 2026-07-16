# Hybrid Recall Engine — Design

**Date:** 2026-07-16
**Status:** Approved (design), pending implementation plan
**Problem:** The reviewer misses defects the lens already covers. Root cause: one context applies ~150 rules (120KB SKILL.md) to the whole diff — attention dilutes, the coverage ledger is self-reported, and the completeness-critic pass shares the blind spots of the pass it audits.
**Decision:** Hybrid engine — deterministic mechanical pre-scan + parallel subagent fan-out over lens slices, with the main context as judge. User accepted the ~4–6× token cost for the recall jump.

## 1. Architecture

Step 8 (reviewer) / the analyze step (fixer) restructures into three phases:

```
Phase 1  scripts/scan_diff.py (extended)  → candidate list (greppable rules, added lines only)
Phase 2  subagent fan-out                 → semantic findings (6 lens slices, parallel, read-only)
Phase 3  main context                     → adjudicate candidates + merge + dedup + dismissal filter + post
```

> Implementation note: the repo already ships `scripts/scan_diff.py` — a diff-scoped, added-lines-only, layer-routed pattern scanner with ignore-marker support, byte-identical in both skills and covering most of the rule table below. Phase 1 **extends it** with the missing rules rather than adding a second scanner (DRY).

The main context stops being the finder and becomes the judge. Both skills get the identical restructure in the same commit; the shared-file no-drift test extends to the new script.

**Fan-out gate:** total changed lines < 25 → skip Phase 2, run today's single-context dimension walk instead (Phase 1 + Phase 3 still run). 25+ → fan out. Slice-level `n/a` skips (see §3) trim cost naturally on top.

## 2. Phase 1 — mechanical scan (extend `scan_diff.py`)

`scripts/scan_diff.py` already covers: dd/dump/die, superglobals, raw-SQL interpolation, debug output, missing return types, `env()` outside config, `Http::` without timeout, controller layering patterns, Service HTTP-agnostic patterns, `$guarded = []`, mass assignment, v-html, console.log (Vue only), Blade `{!! !!}`, migration/test rules.

**Rules to add** (rule_id → dim, severity, pattern intent):

| rule_id | Dim | Sev | Fires on |
|---|---|---|---|
| secret-literal | §3i | MUST | `AKIA[0-9A-Z]{16}`, `-----BEGIN … PRIVATE KEY`, long literal assigned to a secret-ish name |
| select-star | §9 | WARN | `->select('*')`, `DB::raw('select * …')` |
| get-then-pluck | §9 | WARN | `->get()->pluck(` |
| log-getmessage | §10 | WARN | `Log::error($e->getMessage())` and level variants |
| exception-in-response | §3f | MUST | `getMessage()`/`getTraceAsString()`/`getFile()`/`getLine()` inside `response()->json(` / `abort(` |
| *(routing fix)* | §12 | — | plain `.js/.jsx/.ts/.tsx` files currently get **no** JS rules — route console.log/debugger/addEventListener to them |

Full previous table (for reference — rows already covered by existing rules are struck):

| rule_id | Dim | Sev | Fires on |
|---|---|---|---|
| strict-types-missing | §2a | 🟡 | new `app/**.php` file without `declare(strict_types=1)` |
| request-all-mass-assign | §3b | 🟡 | `$request->all()` passed to `create`/`update`/`fill` |
| env-outside-config | §3g | 🟡 | `env(` in a non-`config/` PHP file |
| forbidden-debug | §3h | 🟡 | `dd(`, `dump(`, `die(`, `var_dump(`, `print_r(`, `error_log(` |
| superglobal | §3h | 🟡 | `$_SERVER`, `$_GET`, `$_POST`, `$_REQUEST`, `$_ENV` |
| secret-literal | §3i | 🔴 | `AKIA[0-9A-Z]{16}`, `-----BEGIN`, long high-entropy string literals assigned to key-ish names |
| guarded-empty | §4d | 🟡 | `$guarded = []` |
| http-no-timeout | §9 | 🟡 | `Http::` call chain with no `timeout(` on the added lines |
| select-star | §9 | 🔵 | `->select('*')`, `DB::raw('select *')` |
| get-then-pluck | §9 | 🔵 | `->get()->pluck(` |
| log-getmessage | §10 | 🔵 | `Log::error($e->getMessage())` and variants |
| exception-in-response | §3f | 🟡 | `getMessage()` / `getTraceAsString()` inside `response()->json(` / `abort(` |
| v-html | §12 | 🔴 | added `v-html` |
| blade-raw-echo | §15 | 🔴 | added `{!! !!}` |
| console-log | §12 | 🔵 | added `console.log(` |

Output: JSON array `[{file, line, dim, severity, rule_id, excerpt}]` to stdout, human summary to stderr. These are **candidates, not findings** — precision lives in Phase 3, so the patterns stay simple and recall-biased. Adding a rule = one table entry + one unit test.

## 3. Phase 2 — subagent fan-out

Six read-only subagents launched in parallel, one per lens slice:

| Slice | Dimensions | Skip when |
|---|---|---|
| S1 | §1 Architecture, §4 Laravel, §5 Models | — |
| S2 | §3 Security, §7 Correctness, §8 Data integrity | — |
| S3 | §2 Standards & readability | — |
| S4 | §9 Performance, §10 Error handling, §16 Scalability | — |
| S5 | §12 Front-end, §15 Blade | no JS/TS/Vue/Blade file changed |
| S6 | §6 Enums, §11 Migrations, §13 Testing, §14 API design | per-dimension `n/a` by changed file types |

Each agent receives:
- worktree path + changed-file list + instruction to read hunks first (same diff-first discipline as today)
- **only its slice's lens text** (~20 rules — the recall mechanism: full attention per rule)
- project `CLAUDE.md` override rules relevant to its dimensions
- the implementation-context block (Step 4c), with the existing discipline: context can dismiss style-level doubts, never launder 🔴
- a strict output contract: JSON findings `{file, line, dim, severity, title, body}` **plus** a per-dimension ledger fragment (`✓ clean` / `✓ N findings` / `n/a — no files in scope`)

Agents do not post, write, or read dismissals — they only report.

## 4. Phase 3 — merge & arbitration (main context)

1. **Adjudicate every Phase 1 candidate** — confirm as a finding or reject with a stated reason (exemptions live here: `print_r($x, true)` into a `Log::` call, `env()` in `config/`, seeded test secrets, etc.). Silent drops forbidden.
2. **Merge agent findings.** Dedup rule: same file, lines within ±5, same dim → keep the more specific / higher-severity finding.
3. **Existing filters unchanged:** dismissal memory (`.ai-review/dismissals.json` ±5 lines), implementation-context discipline, protected-branch refusal.
4. **Coverage ledger v2:** one row per dimension — status plus source (`script` / `S2 agent` / `inline fallback`). Printed before posting, as today.
5. Compile by severity and continue into each skill's unchanged downstream steps (reviewer: post to Bitbucket; fixer: present/apply locally).

## 5. Failure & cost handling

- **Agent slice fails or Agent tool unavailable** (some headless environments): that slice falls back to today's inline dimension walk in the main context; ledger marks `inline fallback`. The engine never performs worse than current behaviour.
- **Script fails:** warn, skip Phase 1, Phase 2 still runs.
- **Cost floor:** every 25+-line review pays ~4–6× diff-read cost. Accepted trade (user decision: recall over spend).
- **CI/headless:** Claude Agent SDK supports subagents — the same flow carries into the pipeline product unchanged.

## 6. Testing & shipping

- Unit tests for the new `scan_diff.py` rules: fixture diffs asserting each rule fires, plus non-fire cases for the documented exemptions (e.g. `env()` inside `config/` — existing behaviour — and `Log::error('msg', ['exception' => $e])` not firing log-getmessage).
- `TestSharedFilesNoDrift` already covers `scan_diff.py`; build idempotency test unchanged.
- Both `SKILL.template.md` files updated in the same commit (fixer-alignment rule). `python3 build.py` regenerates both SKILL.md outputs.
- README: new "How a review runs" phase description. Minor version bumps for both skills.

## Out of scope

- Changing lens content or severities (separate workstream).
- Multi-turn agent debate / adversarial verification of findings (possible later phase; Phase 3 arbitration is the v1 quality gate).
- The CI Slice 2 pipeline build itself.
