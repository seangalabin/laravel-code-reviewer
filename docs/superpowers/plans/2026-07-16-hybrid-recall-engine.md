# Hybrid Recall Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the reviewer's recall against its own lens by restructuring the analyze step into three phases: extended mechanical pre-scan → parallel lens-slice subagent fan-out → main-context arbitration.

**Architecture:** Phase 1 extends the existing `scripts/scan_diff.py` (diff-scoped regex scanner, byte-identical in both skills) with five missing rules + a JS-file routing fix. Phase 2/3 are prompt-engineering changes to `skill/SKILL.template.md` Step 8 and `skill-fixer/SKILL.template.md` Step 4: on diffs ≥25 changed lines, spawn six read-only subagents (one lens slice each), then the main context adjudicates every scan candidate, merges/dedups agent findings, and continues into unchanged downstream steps.

**Tech Stack:** Python 3 stdlib (script + unittest), Markdown templates expanded by `build.py`.

**Spec:** `docs/superpowers/specs/2026-07-16-hybrid-recall-engine-design.md`

## Global Constraints

- Read VERSION from git HEAD before bumping: `git show HEAD:skill/VERSION` / `git show HEAD:skill-fixer/VERSION`. Never bump from memory.
- Both skills change in the same commit (fixer-alignment rule). `scripts/scan_diff.py` must stay **byte-identical** across `skill/` and `skill-fixer/` — `TestSharedFilesNoDrift` enforces.
- After ANY `*.template.md` or `src/review-lens.md` edit: run `python3 build.py` and commit the regenerated `SKILL.md` files with it.
- Full suite must pass at the end of every task: `python3 -m unittest discover -s tests -q` (67 tests before this plan).
- Commits: no Co-Authored-By lines. Do NOT push — the user reviews then approves pushes.
- All commands run from repo root `/home/dev5/Documents/claude-code-reviewer`.

## Pre-flight gate (before Task 1)

The working tree may hold **unshipped, unrelated changes** (lens rules A2–A9 + CLAUDE.md consolidation, versions already bumped to 1.37.0/1.33.0 in-tree). Run `git status --porcelain`. If dirty: STOP and ask the user to ship or stash those first. This plan's commits must not mix with them. Version bumps in Task 4 assume those shipped as 1.37.0/1.33.0; if they were discarded instead, adjust the "next minor" accordingly (always from `git show HEAD:...`).

---

### Task 1: Extend scan_diff.py — new rules, JS routing, testable scan_text()

**Files:**
- Modify: `skill/scripts/scan_diff.py`
- Copy to: `skill-fixer/scripts/scan_diff.py` (byte-identical)
- Test: `tests/test_scripts.py` (append a new test class)

**Interfaces:**
- Consumes: existing `parse_diff(diff_text)`, `select_rules(path)`, `Finding` dataclass, `has_ignore_marker_above(path, line)`.
- Produces: `scan_text(diff_text) -> list[Finding]` — pure function over a unified-diff string (no git subprocess), used by tests and by `scan()`. New rule ids: `secret-literal`, `select-star`, `get-then-pluck`, `log-getmessage`, `exception-in-response`. New rules list `JS_RULES` routed to `.js/.jsx/.ts/.tsx` and included in `VUE_RULES` coverage.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scripts.py` (the file already loads the module as `scan_diff` via `load_module(SCRIPTS / 'scan_diff.py', 'scan_diff')` at the top):

```python
# ── scan_diff — hybrid-recall rules ───────────────────────────────────────────

def _mkdiff(path: str, *added_lines: str) -> str:
    """Minimal unified diff adding the given lines to `path`."""
    body = '\n'.join('+' + l for l in added_lines)
    return (
        f'diff --git a/{path} b/{path}\n'
        f'--- a/{path}\n'
        f'+++ b/{path}\n'
        f'@@ -0,0 +{len(added_lines)} @@\n'
        f'{body}\n'
    )


class TestScanDiffHybridRules(unittest.TestCase):

    def rules_hit(self, diff_text):
        return {f.rule for f in scan_diff.scan_text(diff_text)}

    # scan_text is a pure function over the diff string
    def test_scan_text_exists_and_returns_findings(self):
        diff = _mkdiff('app/Services/Foo.php', '        dd($x);')
        hits = self.rules_hit(diff)
        self.assertIn('no-dd-dump-die', hits)

    # secret-literal (§3i)
    def test_secret_literal_aws_key(self):
        diff = _mkdiff('app/Services/S3.php', "$key = 'AKIAIOSFODNN7EXAMPLE';")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_private_key_block(self):
        diff = _mkdiff('config/keys.php', "'pem' => '-----BEGIN RSA PRIVATE KEY-----',")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_named_secret_assignment(self):
        diff = _mkdiff('app/Services/Pay.php',
                       "$apiSecret = 'sk_live_51Hx9aBcDeFgH1234567890';")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_ignores_short_and_unnamed(self):
        diff = _mkdiff('app/Services/Pay.php', "$mode = 'live';")
        self.assertNotIn('secret-literal', self.rules_hit(diff))

    # select-star (§9)
    def test_select_star_quoted(self):
        diff = _mkdiff('app/Repositories/R.php', "->select('*')")
        self.assertIn('select-star', self.rules_hit(diff))

    def test_select_star_db_raw(self):
        diff = _mkdiff('app/Repositories/R.php', 'DB::raw("SELECT * FROM users")')
        self.assertIn('select-star', self.rules_hit(diff))

    def test_select_columns_not_flagged(self):
        diff = _mkdiff('app/Repositories/R.php', "->select(['id', 'name'])")
        self.assertNotIn('select-star', self.rules_hit(diff))

    # get-then-pluck (§9)
    def test_get_then_pluck(self):
        diff = _mkdiff('app/Repositories/R.php', "$ids = $q->get()->pluck('id');")
        self.assertIn('get-then-pluck', self.rules_hit(diff))

    def test_builder_pluck_not_flagged(self):
        diff = _mkdiff('app/Repositories/R.php', "$ids = $q->pluck('id');")
        self.assertNotIn('get-then-pluck', self.rules_hit(diff))

    # log-getmessage (§10)
    def test_log_getmessage(self):
        diff = _mkdiff('app/Services/S.php', 'Log::error($e->getMessage());')
        self.assertIn('log-getmessage', self.rules_hit(diff))

    def test_log_with_exception_context_not_flagged(self):
        diff = _mkdiff('app/Services/S.php',
                       "Log::error('charge failed', ['exception' => $e]);")
        self.assertNotIn('log-getmessage', self.rules_hit(diff))

    # exception-in-response (§3f)
    def test_exception_in_json_response(self):
        diff = _mkdiff('app/Http/Controllers/C.php',
                       "return response()->json(['error' => $e->getMessage()], 500);")
        self.assertIn('exception-in-response', self.rules_hit(diff))

    def test_exception_in_abort(self):
        diff = _mkdiff('app/Http/Controllers/C.php', 'abort(500, $e->getMessage());')
        self.assertIn('exception-in-response', self.rules_hit(diff))

    def test_reported_exception_not_flagged(self):
        diff = _mkdiff('app/Http/Controllers/C.php', 'report($e);')
        self.assertNotIn('exception-in-response', self.rules_hit(diff))

    # JS routing fix (§12)
    def test_console_log_in_plain_js(self):
        diff = _mkdiff('resources/js/store/modules/agents.js', "console.log(state);")
        self.assertIn('no-console-log', self.rules_hit(diff))

    def test_debugger_in_ts(self):
        diff = _mkdiff('resources/js/helpers/date.ts', 'debugger;')
        self.assertIn('no-debugger', self.rules_hit(diff))

    def test_vue_rules_still_apply_to_vue(self):
        diff = _mkdiff('resources/js/components/A.vue', '<div v-html="userBio">')
        self.assertIn('v-html', self.rules_hit(diff))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_scripts.TestScanDiffHybridRules -v 2>&1 | tail -8`
Expected: FAIL / ERROR — `AttributeError: module 'scan_diff' has no attribute 'scan_text'` (every test).

- [ ] **Step 3: Implement in `skill/scripts/scan_diff.py`**

3a. Refactor `scan(base_ref)` so the loop body becomes a pure function. Replace the current `scan()` body after the subprocess call with a call to `scan_text(diff)`:

```python
def scan_text(diff_text: str):
    """Pure scanner over a unified-diff string — no git, no exit()."""
    findings: list[Finding] = []
    for path, lineno, content in parse_diff(diff_text):
        if any(s in path for s in ("vendor/", "storage/", "node_modules/")):
            continue
        if has_ignore_marker_above(path, lineno):
            continue
        for severity, rule_id, pattern, message, predicate in select_rules(path):
            m = pattern.search(content)
            if not m:
                continue
            if predicate and not predicate(m, content):
                continue
            findings.append(Finding(
                path=path, line=lineno, severity=severity, rule=rule_id,
                message=message, snippet=content.strip()[:160],
            ))
    return findings


def scan(base_ref: str):
    cmd = ["git", "diff", f"{base_ref}...HEAD", "--unified=0", "--no-color"]
    try:
        diff = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"error: {' '.join(cmd)} failed:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    return scan_text(diff)
```

> Keep the exact `cmd` construction currently in `scan()` — copy it verbatim from the existing function (it may differ from the line above; the existing behaviour wins). Only the post-subprocess body moves into `scan_text`.

3b. Add to `ALWAYS_RULES` (fires on every file type):

```python
    ("MUST", "secret-literal",
     re.compile(
         r"AKIA[0-9A-Z]{16}"
         r"|-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY"
         r"|(?i:secret|api[_-]?key|token|passwd|password)\w*['\"]?\s*(?:=|=>|:)\s*['\"][A-Za-z0-9+/_\-]{20,}['\"]"
     ),
     "possible hardcoded secret/credential — move it to config/credential storage; rotate if already committed", None),
```

3c. Add to `PHP_RULES`:

```python
    ("WARN", "select-star",
     re.compile(r"->select\s*\(\s*['\"]\*['\"]|DB::raw\s*\(\s*['\"](?i:select\s+\*)"),
     "explicit select('*') — redundant; list only the columns actually used (keep id + FKs + accessor/cast sources)", None),

    ("WARN", "get-then-pluck",
     re.compile(r"->get\s*\(\s*\)\s*->pluck\s*\("),
     "->get()->pluck() loads every column then plucks — call ->pluck() on the builder instead", None),

    ("WARN", "log-getmessage",
     re.compile(r"Log::(?:error|warning|critical|info)\s*\(\s*\$\w+->getMessage\s*\("),
     "Log::*($e->getMessage()) flattens the exception and drops the trace — prefer report($e), or pass ['exception' => $e]", None),

    ("MUST", "exception-in-response",
     re.compile(r"(?:response\s*\(\s*\)->json|abort)\s*\(.*->get(?:Message|TraceAsString|File|Line)\s*\("),
     "raw exception detail in an HTTP response — leaks internals to the client; return a generic message and report($e) instead", None),
]
```

(Watch the closing bracket — the snippet above shows the new entries ending the existing `PHP_RULES` list; don't duplicate the `]`.)

3d. Add `JS_RULES` right after `VUE_RULES` and reuse the shared entries — move `no-console-log`, `no-debugger`, and `add-event-listener` out of `VUE_RULES` into `JS_RULES`, then compose:

```python
JS_RULES = [
    ("WARN", "no-console-log",
     re.compile(r"\bconsole\.(?:log|debug)\s*\("),
     "console.log/debug in committed code", None),

    ("WARN", "no-debugger",
     re.compile(r"\bdebugger\s*[;\n]"),
     "debugger statement in committed code", None),

    ("WARN", "add-event-listener",
     re.compile(r"\baddEventListener\s*\("),
     "addEventListener — verify a matching removeEventListener exists in beforeUnmount()/destroyed() to prevent memory leaks", None),
]

VUE_RULES = JS_RULES + [
    ("MUST", "v-html",
     re.compile(r"\bv-html\s*="),
     "v-html — XSS risk if the value is not sanitised before assignment (DOMPurify or trusted internal source only)", None),

    ("MUST", "direct-store-mutate",
     re.compile(r"\$store\.state\.[A-Za-z_][\w.]*\s*="),
     "direct Vuex state mutation — use commit('mutation') so DevTools tracks the change", None),

    ("WARN", "key-is-index",
     re.compile(r":key\s*=\s*[\"']?\s*index\s*[\"']?|:key\s*=\s*\"\s*\$index\s*\""),
     ":key bound to loop index — use a stable unique ID (record.id) so Vue patches the right instances when items reorder", None),

    ("WARN", "direct-dom",
     re.compile(r"\bdocument\.(querySelector|getElementById|getElementsBy)\s*\("),
     "direct DOM manipulation in Vue — use this.$refs.name instead so Vue controls the element lifecycle", None),
]
```

(These four are the existing `VUE_RULES` entries verbatim — the net change is: three entries move to `JS_RULES`, `VUE_RULES` becomes `JS_RULES + [the four above]`.)

3e. In `select_rules(path)`, add JS routing before the `.vue` check:

```python
    if path.endswith((".js", ".jsx", ".ts", ".tsx")):
        rules += JS_RULES
```

- [ ] **Step 4: Sync the fixer copy**

Run: `cp skill/scripts/scan_diff.py skill-fixer/scripts/scan_diff.py`

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests -q 2>&1 | tail -3`
Expected: `OK`, test count 67 + 18 new = 85. (`TestSharedFilesNoDrift` confirms the copies match.)

- [ ] **Step 6: Commit**

```bash
git add skill/scripts/scan_diff.py skill-fixer/scripts/scan_diff.py tests/test_scripts.py
git commit -m "scan_diff: add secret-literal, select-star, get-then-pluck, log-getmessage, exception-in-response rules; route JS rules to plain .js/.ts files; extract pure scan_text() for tests"
```

---

### Task 2: Reviewer template — three-phase Step 8

**Files:**
- Modify: `skill/SKILL.template.md` (Step 8 — Analyze, items 6–8)
- Regenerate: `skill/SKILL.md`, `skill-fixer/SKILL.md` (via `python3 build.py`)

**Interfaces:**
- Consumes: existing Step 8 structure (items 1–10), `scan_diff.py` output format (`+LINE TAG rule: message` text), the lens dimension numbering §1–§16.
- Produces: the phase structure and slice table that Task 3 mirrors into the fixer; ledger-v2 format (`| Dim | Status | Source |`).

- [ ] **Step 1: Replace items 6–8 of Step 8**

In `skill/SKILL.template.md`, find item 6 (`**Apply the full review lens dimension by dimension — do not free-associate.**`), item 7 (`**Build a coverage ledger.**`), and item 8 (`**Completeness critic — second pass over the gaps.**`) inside `### Step 8 — Analyze`, and replace those three items with the following (keeping items 9 and 10 — renumber them 8 and 9):

```markdown
6. **Choose the analysis mode.** Count the diff's changed lines (`git diff --shortstat` insertions + deletions, or the scoping script's total). **Under 25 changed lines** → run the *inline walk* described in 7a. **25 or more** → run the *fan-out* described in 7b. Either way, the `scan_diff.py` pre-pass output from the scoping step is Phase 1 input to item 8.

7a. **Inline walk (small diffs).** Apply the full review lens dimension by dimension — do not free-associate. Walk the lens in order and, for **each** numbered dimension (§1 Architecture → §16 Scalability) plus the company rules from Step 3, deliberately check the diff against that dimension before moving on. A dimension is only "done" once you've recorded a finding or confirmed the diff is clean for it. Then run a completeness-critic pass: re-scan the diff once more focused only on dimensions you marked clean — "genuinely fine, or did I skim?" Watch the easily-missed: §2i magic literals, §2m `count()` emptiness, §2p name-matches-behaviour, §3i hardcoded secrets, §4b N+1, §10 `report()` on caught exceptions. Ledger `Source` column: `inline`.

7b. **Fan-out (25+ changed lines).** Launch **six parallel read-only subagents** with the Task/Agent tool, one per lens slice:

   | Slice | Dimensions | Skip when |
   |---|---|---|
   | S1 | §1 Architecture, §4 Laravel, §5 Models | — |
   | S2 | §3 Security, §7 Correctness, §8 Data integrity | — |
   | S3 | §2 Standards & readability | — |
   | S4 | §9 Performance, §10 Error handling, §16 Scalability | — |
   | S5 | §12 Front-end, §15 Blade | no JS/TS/Vue/Blade file in the diff |
   | S6 | §6 Enums, §11 Migrations, §13 Testing, §14 API design | mark individual dims n/a when no file in scope |

   Each subagent prompt MUST contain, verbatim where applicable:
   - the working directory (worktree path in target mode) and the changed-file list;
   - the instruction: *"Read the diff hunks first (`git diff {BASE}...HEAD -- {files}`); read surrounding code only for context. Findings are only valid on changed lines or their direct blast radius."*;
   - **only that slice's lens sections**, copied from this skill's lens below, plus any project CLAUDE.md rules touching those dimensions;
   - the implementation-context block from Step 4c if one exists, with the discipline: context may downgrade style-level doubts, it never dismisses a 🔴;
   - the output contract: *"Return ONLY a JSON array of findings `[{file, line, dim, severity, title, body}]` followed by a ledger line per dimension: `§N <name> — ✓ clean | ✓ K findings | n/a — no files in scope`. No prose."*
   - the constraint: read-only — no edits, no posting, no writes.

   If the Agent tool is unavailable or a slice agent errors, **fall back to the inline walk (7a) for that slice's dimensions only** and mark its ledger rows `inline fallback`.

8. **Arbitrate (main context is the judge).**
   - **Adjudicate every `scan_diff.py` line.** Each pre-pass hit must end as either a confirmed finding or a rejection with a stated reason (e.g. "env() hit is in config/ — exempt", "print_r has `true` second arg into Log — exempt"). Silent drops are forbidden; if the pre-pass printed 12 hits, your arbitration must account for 12.
   - **Merge agent findings.** Dedup: same file, same dimension, lines within ±5 → keep the more specific / higher-severity finding. Where an agent finding duplicates a confirmed pre-pass hit, keep one (the better-worded).
   - Re-check each surviving finding's severity against the lens — subagents sometimes inflate; the lens severity wins.
   - **Build the coverage ledger v2** — one row per dimension with its source:

     | Dim | Status | Source |
     |---|---|---|
     | §1 Architecture & layering | ✓ 2 findings | S1 agent |
     | §2 Code standards | ✓ clean | S3 agent |
     | §3 Security | ✓ 1 finding | S2 agent + scan |
     | §15 Blade | n/a — no Blade files changed | — |

     `n/a` only when no changed file is in that dimension's scope. Every dimension must appear.
```

- [ ] **Step 2: Renumber the remaining Step 8 items**

The old items 9 (`**Filter dismissals.**`) and 10 (`**Compile remaining findings**`) contain a self-reference: old item 10 says "print the coverage ledger". Renumber them to 9 and 10 → they stay 9 and 10 if the block above ends at 8 — verify the final sequence reads 1, 2, 3, 4, 5, 6, 7a, 7b, 8, 9, 10 and that no duplicate numbers remain (this template had a duplicate-number regression before; check twice).

- [ ] **Step 3: Rebuild and verify**

Run: `python3 build.py && python3 -m unittest discover -s tests -q 2>&1 | tail -3`
Expected: both SKILL.md regenerate; suite `OK` (85 tests — includes idempotency + drift guards).

Run: `grep -n "7a\.\|7b\.\|Arbitrate" skill/SKILL.md | head`
Expected: the new items present in the built file.

- [ ] **Step 4: Commit**

```bash
git add skill/SKILL.template.md skill/SKILL.md skill-fixer/SKILL.md
git commit -m "reviewer: three-phase analyze — <25-line inline walk, 6-slice subagent fan-out, main-context arbitration with adjudicated scan pre-pass and sourced coverage ledger"
```

(`skill-fixer/SKILL.md` may be byte-unchanged in this commit if build only touched the reviewer — harmless to include.)

---

### Task 3: Fixer template — mirror the three phases

**Files:**
- Modify: `skill-fixer/SKILL.template.md` (Step 4 — Analyze, items 5–7)
- Regenerate: both `SKILL.md` files via `python3 build.py`

**Interfaces:**
- Consumes: the exact phase/slice/arbitration text shipped in Task 2 (same slice table, same ledger v2, same 25-line gate).
- Produces: fixer parity — analysis phases identical; downstream difference stays: fixer presents/applies locally instead of posting.

- [ ] **Step 1: Replace items 5–7 of fixer Step 4**

In `skill-fixer/SKILL.template.md` `### Step 4 — Analyze`, item 5 (`**Apply the full review lens dimension by dimension…**`), item 6 (`**Build a coverage ledger**…`), and item 7 (`**Completeness critic…**`) are replaced with the same block as Task 2's Step 1, adapted only in these ways:
- item numbers: `5.` (mode choice), `6a.` (inline walk), `6b.` (fan-out), `7.` (arbitrate);
- "company rules from Step 3" → "company rules from Step 2";
- "the implementation-context block from Step 4c" → "the implementation-context block from Step 3c";
- the scan pre-pass reference points at the fixer's scoping step (its `scan_diff.py` invocation is in Step 4's earlier items — keep the wording "the `scan_diff.py` pre-pass output from the scoping step").

Everything else — slice table, agent prompt contract, output contract, fallback, adjudication, dedup, ledger v2 — must be copied **verbatim** from Task 2. Divergent wording here is drift; the two blocks should differ only in the four points above.

- [ ] **Step 2: Verify the "Print the coverage ledger" line**

Fixer Step 4 ends with "Print the coverage ledger, then a brief summary once analysis is done". Update it to "Print the coverage ledger v2 (with Source column), then a brief summary once analysis is done".

- [ ] **Step 3: Rebuild and verify**

Run: `python3 build.py && python3 -m unittest discover -s tests -q 2>&1 | tail -3`
Expected: `OK`.

Run: `grep -n "6a\.\|6b\.\|Arbitrate" skill-fixer/SKILL.md | head`
Expected: new items present.

- [ ] **Step 4: Commit**

```bash
git add skill-fixer/SKILL.template.md skill-fixer/SKILL.md skill/SKILL.md
git commit -m "fixer: mirror three-phase analyze (25-line gate, 6-slice fan-out, arbitration + sourced ledger) — parity with reviewer"
```

---

### Task 4: README, versions, final verification

**Files:**
- Modify: `README.md`
- Modify: `skill/VERSION`, `skill-fixer/VERSION`

**Interfaces:**
- Consumes: shipped HEAD versions (`git show HEAD:skill/VERSION`, `git show HEAD:skill-fixer/VERSION`).
- Produces: next minor of each (e.g. 1.37.0 → 1.38.0, 1.33.0 → 1.34.0 — compute from HEAD, do not trust these examples).

- [ ] **Step 1: README — describe the engine**

In `README.md`, find the section describing how a review runs (the part covering the dimension walk / coverage ledger — `grep -n "coverage ledger\|dimension" README.md`). Update it to describe the three phases in ~5 lines:

```markdown
Reviews run as a three-phase engine: (1) a mechanical pre-pass (`scan_diff.py`)
greps the diff's added lines for ~40 known red-flag patterns; (2) on diffs of
25+ changed lines, six parallel read-only subagents each sweep one slice of the
lens (~20 rules of full attention instead of ~150); (3) the main context
adjudicates every pre-pass hit (confirm or reject with a reason — silent drops
forbidden), merges and dedups agent findings, and prints a coverage ledger
showing every dimension's status and source. Small diffs use a single inline pass.
```

- [ ] **Step 2: Bump versions from HEAD**

```bash
git show HEAD:skill/VERSION        # e.g. 1.37.0
git show HEAD:skill-fixer/VERSION  # e.g. 1.33.0
printf '<next-minor-of-skill>\n'   > skill/VERSION
printf '<next-minor-of-fixer>\n'   > skill-fixer/VERSION
```

- [ ] **Step 3: Full verification**

```bash
python3 build.py
python3 -m unittest discover -s tests -q 2>&1 | tail -3
git status --porcelain   # only README.md, both VERSIONs (+ SKILL.md if build changed anything)
```

Expected: `OK` (85 tests), no unexpected dirty files.

Smoke-check the built prompt: `grep -c "fan-out\|Adjudicate every" skill/SKILL.md` → ≥ 2.

- [ ] **Step 4: Commit**

```bash
git add README.md skill/VERSION skill-fixer/VERSION skill/SKILL.md skill-fixer/SKILL.md
git commit -m "Hybrid recall engine: document three-phase review in README; bump skill <X> / skill-fixer <Y>"
```

- [ ] **Step 5: Report — do not push**

Summarize the four commits to the user and wait for push approval (house rule).

---

## Post-plan (not tasks — context for the executor)

- **Live validation** (after user pushes + updates an install): run `/code-reviewer` against a real PR ≥25 changed lines; confirm the ledger shows agent sources and the scan adjudication accounts for every hit. This is a user-driven step.
- Out of scope per spec: lens content changes, adversarial verification of findings, CI Slice 2.
