# Changelog

This repo ships two independently-versioned skills — **code-reviewer** and **code-fixer**
(see [Versioning](README.md#versioning)). Each entry below is tagged with the skill it
applies to and its `VERSION` at that release. Versions follow [semver](https://semver.org/);
the format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## code-reviewer 1.63.1 / code-fixer 1.57.1 — 2026-08-11

### Changed
- **§2a legacy-retrofit suggestions are now self-guarding.** Before suggesting
  `declare(strict_types=1)` on an edited legacy file, the reviewer must scan that file for
  §7 runtime-data boundaries (`json_decode()`, raw payloads, `unserialize()`, external API
  responses feeding scalar-typed parameters) and name them in the finding, requiring those
  call sites be normalized *first* — otherwise the suggestion guides the developer into the
  intermittent `TypeError` crash instead of around it. A clean scan is stated explicitly so
  the developer knows it happened. Shared-lens change — both skills.

## code-reviewer 1.63.0 / code-fixer 1.57.0 — 2026-08-11

### Added
- **§7 strict-types boundary rule.** New correctness bullet: runtime-untyped data
  (`json_decode()`, raw request/JSON payloads, `unserialize()`, CSV, external API responses)
  passed to a scalar-typed parameter **from inside a `strict_types` file** — 🟡, escalating to
  🔴 when the unguarded throw sits on a request path. Under strict mode coercion no longer
  rescues a numeric string, so the call throws `TypeError` only on payloads that happen to
  carry strings — an intermittent production crash. Remedy: normalize at the boundary
  (`is_numeric()` + cast, or a DTO/cast layer). Scoped tightly: fires only when the calling
  file declares strict_types and the value provenance is runtime data — Eloquent-cast, DTO,
  and validated-FormRequest values don't count. Shared-lens change — both skills.

## code-reviewer 1.62.0 / code-fixer 1.56.0 — 2026-08-07

### Fixed
- **Incremental review no longer reviews code that rode in via a merge from the base
  branch.** In checkpoint mode the diff base is an ancestor of HEAD, so `checkpoint...HEAD`
  contains *everything reachable since the checkpoint* — including the entire base-branch
  delta whenever the developer merges the base into the branch. The reviewer then flagged
  other people's already-integrated code as if the PR changed it ("findings not part of the
  recent commits", varying run to run). Now, when merges exist in the checkpoint range, the
  scope is restricted to **branch-own files** (`git log checkpoint..HEAD --not origin/$BASE
  --no-merges --name-only`), with narration of how many files were excluded; a push that is
  *only* a merge commit short-circuits like the 0-new-commits case (replies + Jira sync,
  stop). `scan_diff.py` gains a `--files` filter for the same scoping (both copies, kept
  byte-identical). The scope rule states it explicitly: findings anchor to branch-own
  commits; merged-in base-branch code is out of scope even though it appears in the diff.
  Full-review mode was never affected (three-dot vs the base excludes it via the merge-base).
  Reviewer template change (the fixer always diffs the base branch and is merge-base-safe);
  `code-fixer` bumps in lockstep for the shared `scan_diff.py`.

## code-reviewer 1.61.0 / code-fixer 1.55.0 — 2026-08-07

### Added
- **§9 Existence checks — `->exists()`, not a count** (canonical for "does any row match?").
  Replaces the narrower `->get()` then `->isEmpty()` / `->count()` bullet, which only caught
  the hydration case and named builder-level `->count()` as an acceptable fix. Three shapes,
  graded by what the database actually does:
  - `count($user->orders) > 0` / `$user->orders->count() > 0` / `->get()` then `->isEmpty()` —
    hydrates **every** matching row into models to answer a yes/no question. 🟡 Warning on an
    unbounded / growing relation, 🔵 on a small reference set.
  - `$user->orders()->count() > 0` — 🔵 Suggestion. No hydration, but `select count(*)` still
    counts every matching row.
  - `$user->orders()->exists()` / `->doesntExist()` — the target: `EXISTS` lets the database
    stop at the first match, so the gap widens with row count and holds even on an indexed
    column.

  Two carve-outs keep it from over-firing: only flag when **the number itself is unused** (a
  count that is displayed, logged, returned, or compared against anything but zero is a
  count), and never suggest `exists()` immediately before a write — `->exists()` then
  `->create()` is the check-then-act race §8 already owns, whose fix is `firstOrCreate()`.

### Changed
- **§2m scoped to in-memory data** and cross-referenced to §9. It advises `isEmpty()` /
  `empty()` for a loaded array or collection; without the pointer it could be read as
  licensing a `->get()` to satisfy a builder-level count, which is the opposite of the
  intent.
- **Step 8's easily-missed list** now names §9 existence checks in place of §2m — the
  canonical rule moved, and that list is what the completeness-critic pass re-checks.

## code-reviewer 1.60.1 — 2026-08-07

### Changed
- **`AI_REVIEW_MAX_USD` default raised 2.00 → 5.00.** A real pipeline review was killed
  mid-flight by the 2.00 cap: 30 turns, 2.06M cache-read + 178k cache-write input tokens,
  21k output, terminated at `error_max_budget_usd` having posted nothing. The cap is a
  runaway killswitch, not a budget, and set that tight it converted a working review into
  pure waste — the run consumed the quota either way.

  Two corrections to what this file previously documented, both from measured data:
  - **The figure is computed at standard Sonnet rates ($3/$15), not the introductory
    $2/$10.** The arithmetic matches `$2.0464929` exactly at standard and $1.3643 at
    introductory. Since `--max-budget-usd` gates on this number, introductory pricing has
    no bearing on whether a run survives — the earlier "~$1–1.60 per run" note was
    measuring the wrong thing and is why the default was set too low.
  - **Cache *writes* were 52% of the cost**, not reads. The CLI uses a 1-hour cache TTL
    billed at 2× input, while a CI container lives ~5 minutes and never reuses the entry.
    At a 5-minute TTL (1.25×) the same run would have cost $1.65 and finished inside the
    old cap. No CLI flag shortens it — verified against 2.1.224, where `--max-budget-usd`
    is also the *only* run-level ceiling; there is no token-denominated equivalent.

  On subscription auth none of this is an invoice: the dollar figure is a synthetic
  yardstick and the real constraint is the account's usage quota. The dollar cap is simply
  the only proxy the CLI exposes for bounding it.

## code-reviewer 1.60.0 — 2026-08-07

Continuous review is the intended model — every push, like CodeRabbit. 1.58.0 quietly
optimised against the opposite assumption; this corrects that and makes the every-push
cadence cheap instead of rare.

### Fixed
- **The CI batching example shipped broken in 1.59.0.** Two defects, both in guidance
  rather than executed code, so nothing crashed — but the advice was wrong for the only
  mode CI ever uses. (1) It set a `S=…` shell shorthand in one Bash block and used it in
  the next; each Bash call is a fresh shell, so the second block expanded to
  `/check_resolved.py` and the whole batch would fail. (2) It used normal-mode relative
  paths while `ai-review-ci` always passes `--pr`/`--branch`, so target mode is always
  active — and `get_checkpoint.sh` reads `.ai-review/target.json` relative to the working
  directory, silently missing it from the main repo. Both blocks now `cd "$WORKTREE"` and
  use `$SKILLS_ROOT`, per the Step 2 rule table, with the independent fetches separated by
  `;` rather than `&&` so one failure doesn't suppress the rest.

### Added
- **Pre-flight skip in `ai-review-ci` — no-op builds now cost zero tokens.** In the
  every-push model a share of builds have nothing new. The skill already detected that,
  but only at the scoping step *inside* the Claude run, after the skill, worktree, card
  context and three comment fetches had loaded — a double-digit number of turns to
  conclude "nothing to do". The gate reaches the same conclusion with three Bitbucket API
  calls and no model invocation. It skips only when **both** hold: the checkpoint SHA
  equals HEAD, and no developer reply is awaiting an answer. The second condition is
  load-bearing — a64e0f3 exists because a 0-commit rerun must still handle replies, and
  skipping one with a pending reply would leave a developer talking to nobody. The Jira
  card is still synced on the skip path (pure Python, idempotent, soft-fails). Fails
  **open** at every branch: a missing script, non-zero exit, or unparseable output runs
  the review, because a gate that wrongly skips is far worse than one that wrongly runs.
  Bypass with `AI_REVIEW_NO_PREFLIGHT=1`. Behaviour verified across seven cases.

### Changed
- **`assets/bitbucket-pipelines.example.yml` defaults to every-push again.**
  1.58.0 made the on-demand `custom:` pipeline the default and commented every-push out as
  "expensive — opt in deliberately". That misrepresented the product to anyone installing
  fresh. `pull-requests: '**'` is the default once more, with the manual pipeline offered
  alongside it for re-runs, and the cost guidance reframed from "don't do this" to what
  keeps it affordable — incremental review plus the pre-flight skip — with branch-scoping
  as the lever if the push rate is still too high.

## code-reviewer 1.59.1 / code-fixer 1.54.1 — 2026-08-07

Repository audit. Docs and packaging only — no behaviour change in either skill.

### Removed
- **`docs/superpowers/` (hybrid-recall engine plan + design spec).** The work shipped —
  `TestScanDiffHybridRules` covers it with 26 test methods — but the plan's 19 checkboxes were
  never ticked, so it read as outstanding. More importantly it was obsolete: the design's
  stated decision is *"parallel subagent fan-out over lens slices … User accepted the ~4–6×
  token cost"*, and a plan step says "Replace items 6–8 of Step 8" — the Step 8 layout deleted
  in 1.55.0 when fan-out was removed. Following it would have reintroduced the architecture
  behind the July–August quota blowup. Nothing referenced either file; history is in git.
- **`.npmignore`.** Exact duplicate of the `files[]` negations in `package.json`
  (`__pycache__/`, `*.pyc`, `*.template.md`); its only unique entry, `*.pyo`, lives inside
  `__pycache__/` and was already covered.

### Fixed
- **README described fan-out as live** — "the fan-out slice agents are always Sonnet" — three
  releases after 1.55.0 removed it. Now states the single-agent policy. Third stale fan-out
  claim found; the other two went in 1.58.0.
- **`skill-fixer/bin/ai-review` docstring named the wrong skill** — "helper for the
  code-reviewer skill", installed at `.claude/skills/code-reviewer/bin/ai-review`. It installs
  to `code-fixer`. Docstring only; no runtime path reads it.

- **The installer shipped build inputs into every install** (`bin/install.js`, bundle 1.2.0).
  `copyDir` had no filter, and it reads neither `package.json`'s `files[]` nor `.npmignore` —
  those apply only to an npm tarball, while the real path is `npx github:…` → this script. So
  a 50KB `SKILL.template.md` (30KB for the fixer) landed in every installed skill directory,
  where Claude Code never loads it and a maintainer could easily mistake it for the editable
  source. `copyDir` now skips `*.template.md`, `__pycache__/`, `*.pyc`, and `*.pyo`. Found
  while verifying that removing `.npmignore` was inert — it was, but only because the file
  had never been doing the job it looked like it was doing.

### Added
- **README documents `ai-review fix`** alongside `dismiss`. The subcommand has been
  manual-only since 1.22.0 dropped the auto-generated `fix` line from posted comments, and
  nothing documented the manual form — so it read as orphaned code.
- **`TestInstallerExcludesBuildInputs`** — guards the `copyDir` filter above (predicate
  present, actually applied in the loop, and templates still present to exclude). Mutation-
  tested: deleting the filter line fails the suite.
- **Regression guards for the cost controls** (`TestSingleAgentPolicy`,
  `TestCIWrapperCostControls`, `TestCINarrationIsTerse`). Between 2026-07-16 and 2026-08-06,
  four independently reasonable changes compounded into a quota blowup, and each fix is a
  single line in a single file. The lens split was the only one guarded. Now covered:
  the single-agent constraint in all four skill surfaces; fan-out mentioned *only* as a
  prohibition, never as live behaviour; `--disallowedTools Task` present and `Task` absent
  from `ALLOWED_TOOLS`; a `MAX_USD` default that exists, is never empty, and is passed
  unconditionally (the 05ca819 break was a *conditional* arg, not a missing default); and
  the CI narration clause with its batching example and surviving relay lines.
  Each guard names the regression it prevents in its failure message. All seven mutations
  were verified to fail the suite. No version bump — tests are not shipped (`files[]`
  excludes `tests/`), so bumping would prompt users to update for something they never
  receive.

### Audited and deliberately kept
`review-lens.md` tracked 3× (source + two generated skill copies, needed for self-contained
installs, drift-guarded), `scan_diff.py` duplicated byte-identically across both skills
(guarded by `TestSharedFilesNoDrift`), all 16 `.ps1` files (parity with `.sh` is complete in
both skills), and `package.json`'s `files[]` / `prepack` (inert under GitHub-only
distribution, but correct and free to keep).

## code-reviewer 1.59.0 — 2026-08-07

### Changed
- **CI narration is terse, and the state-gathering scripts batch.** The Narration rule
  ("print a one-line header … end each step with a one-line outcome summary … quiet success
  is a regression") is written for a developer watching a run. In CI nobody is, the output
  goes to a pipeline log, and each of those lines costs a turn — and every turn re-reads the
  whole cached prefix, which after Step 8 includes the ~23k-token lens. Under
  `$AI_REVIEW_CI=1` the headers and outcome summaries are now dropped while the
  `🔍 / ✓ / ↷ / ⚠️` relay lines are kept (they are the diagnostic record), and the read-only
  fetches run as two Bash calls instead of six: `get_checkpoint` → `branch_summary` →
  `scan_diff` in one, `check_resolved` / `check_dismissals` / `check_replies` in the other.
  Fetches only — Step 7's reply decisions and the `post_reply.py` / `update_resolved.py`
  calls after them are unchanged, as are the lens walk, arbitration, and coverage ledger.
  Costs +486 tokens of always-loaded preamble to save an estimated 10–14 turns per CI run.
  Interactive runs are unaffected. `code-fixer` is interactive-only (no CI mode) and does
  not change.

### Not done, deliberately
- **No wording pass on the lens.** Evaluated and declined on measurement: pressure language
  is already clean (2 caps `MUST/NEVER/CRITICAL` instances), there is no fat outlier (76
  units, median 855 chars, largest 4.3k, top-10 = 35%), and 84% is prose whose rule text,
  reasons, project context, and boundary examples are all load-bearing. `LENS-TUNING.md`
  has been running this audit continuously. Realistic yield was 2–3% of run cost against
  unmeasurable recall risk — the wrong trade for a file that *is* the specification.
- **No output-compression skill** (e.g. caveman). It compresses output only; output is 27%
  of run cost, its own agentic-run figure is 8.5%, and its ~1–1.5k input tokens per turn
  put the net under 1%. Its evals explicitly do not measure fidelity, and single-line PR
  comments conflict with the four-section comment contract.

## code-reviewer 1.58.0 / code-fixer 1.54.0 — 2026-08-07

Cost pass. Nothing here changes what the reviewer finds — only what it costs to find it.

### Changed
- **The review lens ships as a sidecar file instead of being inlined into `SKILL.md`.**
  New `<!-- lensref:src/review-lens.md -->` build marker: `build.py` writes the fragment to
  `<skill>/review-lens.md` and inlines only a pointer plus a generated dimension index. The
  lens walk now opens it with an explicit `Read`, once per review. Everything in `SKILL.md`
  loads the instant the skill is invoked, so the ~23k-token lens was being paid for by every
  run — including runs that stop at the version check, refuse a protected branch, or find no
  new commits since the checkpoint and never walk the lens at all. Always-loaded preamble:
  **code-reviewer ~35k → ~12k tokens, code-fixer ~35k → ~7k.** `install.js` copies the skill
  directory recursively, so the sidecar ships with no installer change.
- **`ai-review-ci` caps OAuth runs again — one 2.00 default for both auth modes.**
  Since 1.47.1 subscription auth ran uncapped, on the reasoning that a USD ceiling can't bill
  a subscription. True, but it also removed the only runaway killswitch — and on OAuth a
  runaway spends one person's Pro/Max quota, which every pipeline review in the team shares.
  `--max-budget-usd` still terminates the run regardless of who's billed, so it's reinstated
  as a guard rather than a budget. 2.00 is priced off a measured run rather than picked:
  a sonnet review is ~2M cache-read + 150k cache-write input tokens and ~30k output, which
  is ~$1.10 at Sonnet 5's introductory $2/$10 per MTok (through 2026-08-31) and ~$1.60 at the
  standard $3/$15 — so the ceiling sits just above a typical run and trips early on a runaway.
  A large diff can legitimately exceed it; raise `AI_REVIEW_MAX_USD` rather than removing the
  cap, using the new per-run usage block to pick the number.
- **`assets/bitbucket-pipelines.example.yml` no longer defaults to reviewing every push.**
  A review's cost is dominated by fixed overhead — loading the skill, scoping, fetching PR
  state — not by diff size, so a 3-line push costs nearly as much as a 300-line one and the
  trigger sets the bill. The example now ships a `custom: ai-review` pipeline (run on demand,
  resolves the PR from `BITBUCKET_BRANCH`) with the `pull-requests: '**'` trigger present but
  commented out and costed. Step is now a reusable `&ai-review` anchor.

### Added
- **Per-run usage report.** `ai-review-ci` prints a `─── Usage ───` block — input/output
  tokens, cache read vs write, turns, duration, estimated spend — parsed from the run's JSON
  output. Printed before the exit-code check, so a run that died mid-review still reports what
  it spent. Soft-fails on missing or malformed fields. Makes the next cost spike visible in
  the pipeline log of the run that caused it.
- **Build guards for the split** (`tests/test_scripts.py`): sidecars must match their source
  fragment, the generated index must list every dimension, and the lens rules must be *absent*
  from `SKILL.md` — switching `lensref:` back to `include:` silently restores the ~23k-token
  cost, so the suite now fails loudly if it happens.

### Fixed
- README described `claude --print --bare` (the `--bare` flag was dropped in 1.46.1 — it
  stops project skills loading) and "parallel lens-slice subagents on larger diffs" (fan-out
  was removed in 1.55.0). Both corrected.

## code-reviewer 1.57.0 / code-fixer 1.53.0 — 2026-08-06

### Added
- **Daily learning digest (`mine_feedback.py --since-hours N --digest FILE`).**
  `--since-hours 24` scopes mining to yesterday's PR activity (walks the -updated_on sort and
  stops at the window edge); `--digest` writes an email-ready plain-text summary — per-dimension
  lifecycle table, dismissal reasons (each a candidate carve-out), still-open counts by PR, and
  the tune-the-lens call to action. Exits **3** with no file when the window had no activity, so
  a scheduled pipeline can skip sending on quiet days. `LENS-TUNING.md` gains the turnkey
  Bitbucket setup: a `custom: ai-review-daily-digest` pipeline + `email-notify` pipe + daily
  schedule (7am local = pick the matching UTC hour). Reviewer-only; `code-fixer` bumps in
  lockstep, behaviour unchanged.

## code-reviewer 1.56.0 / code-fixer 1.52.0 — 2026-08-06

### Added
- **Learning loop — `mine_feedback.py` + the lens-tuning workflow (`LENS-TUNING.md`).** The
  new script walks the last N PRs and extracts every AI finding's lifecycle — resolved /
  dismissed(+reason) / open — grouped per lens dimension into
  `.ai-review/feedback-report.json` with a summary table. `LENS-TUNING.md` documents the two
  triggers that turn the report into lens changes: scheduled mining (monthly / every ~20
  reviews — high dismissed ratios become carve-outs, recurring dismissal reasons become
  exemptions, resolved ratios prove rules earn their keep) and the escaped-defect postmortem
  (bug reaches staging/prod → which dimension should have caught it → sharpened/new rule).
  All proposals pass the generic-rule standard. Mining script is reviewer-only (Bitbucket
  data); `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.55.1 / code-fixer 1.51.1 — 2026-08-06

### Changed
- **`ai-review-ci` passes `--disallowedTools "Task"` explicitly.** The CLI has no `--no-agent`
  flag; subagent spawning was already denied in CI (`dontAsk` + `Task` absent from the
  allowlist), and the explicit disallow makes the single-agent policy a hard, self-documenting
  block rather than an implicit one. Reviewer-only; `code-fixer` bumps in lockstep, behaviour
  unchanged.

## code-reviewer 1.55.0 / code-fixer 1.51.0 — 2026-08-06

### Removed
- **Subagent fan-out removed — the review is single-agent by policy.** The 25+-line fan-out
  mode (six parallel lens-slice subagents, reviewer 7b / fixer 6b) is gone: observed in
  practice, delegation multiplies token spend without improving judgment (the judgment always
  happened at main-context arbitration anyway). Every diff now runs the dimension-by-dimension
  **lens walk in one context**; large diffs (~300+ lines / 10+ files) chunk by related file
  group with the full lens per group — coverage is preserved by the ledger, not by parallelism.
  Enforced three ways: a new global constraint ("Single agent, always — never use the
  Task/Agent tool"), the analysis step forbidding delegation regardless of diff size, and
  `ai-review-ci` dropping `Task` from its allowlist so `dontAsk` auto-denies any stray spawn
  in CI. Goal: quality review at low cost. Mirrored to both skills.

## code-reviewer 1.54.2 / code-fixer 1.50.2 — 2026-08-06

### Changed
- **Lens audit — scenario-specific residue removed.** Full pass of every rule against the
  standard "rules are generic decision procedures; convention-specific stays, incident-specific
  goes; examples are boundary markers". One offender found: §16g's rationale retold its
  originating incident ("standing production problem in this stack… disks have repeatedly
  bloated"; "exactly how the disks got bloated") — rewritten to the generic reasons (files on
  one server are invisible to others, lost on redeploy/autoscale, fill the host disk). Rule
  trigger, severity, carve-outs, and the `Asset::storage()` convention hook unchanged.
  Everything else audited clean. Shared-lens change — both skills.

## code-reviewer 1.54.1 / code-fixer 1.50.1 — 2026-08-06

### Changed
- **§6a reworded — generic and straightforward.** Dropped the case-specific framing; the rule
  now leads with the test ("purity is not the test; ownership is") and generic examples only.
  Same severity and remedy. Shared-lens change — both skills.

## code-reviewer 1.54.0 / code-fixer 1.50.0 — 2026-08-06

### Added
- **§6a Enums — infrastructure/strategy classifications don't belong on the enum, even when
  pure.** §6 only flagged side-effecting/cross-layer logic, so a pure, declarative method
  encoding an *operational decision* (`usesS3Crops()`, `storageDisk()`, `isMigratedToX()`)
  slid through as a "helper" (observed live on B20-11576's `PropertyDataProvider`). The test
  is now *whose fact is it*: intrinsic-to-the-case (label, key, display, domain grouping)
  stays; a strategy/infra/migration classification is 🔵 — move it to the service that
  implements the strategy (as a const/config it owns) or `config/`. Rationale in the rule:
  enums are the most stable layer, strategy flags the least; domain→infra coupling; enums
  accreting into config tables. Shared-lens change — both skills.

## code-reviewer 1.53.4 / code-fixer 1.49.4 — 2026-08-05

### Fixed
- **Jira sync also runs on 0-new-commit reruns.** The checkpoint short-circuit ("no new
  commits → handle replies, stop") stopped **before Step 10**, so the very flow where a
  developer replies and the reviewer concedes/resolves on the rerun could never advance the
  card — the exact scenario 1.53.3 addressed inside Step 10 was still unreachable from this
  path. The short-circuit now runs Step 7 → Step 10 → stop. Reviewer-only; `code-fixer`
  bumps in lockstep, behaviour unchanged.

## code-reviewer 1.53.3 / code-fixer 1.49.3 — 2026-08-05

### Fixed
- **Step 10 (Jira sync) must always run, and conceded findings count as not-open.** Observed
  live: the reviewer conceded a PR's only finding, then *skipped* Step 10 by its own judgment
  ("moving to Failed Code Review would be wrong") — stranding the card in `Code Review` when
  the correct outcome was `has_open_findings=false` → `Ready To Test`. Step 10 now states
  explicitly: a Step 7 concession is a dismissal (and even if the dismissal side effect
  failed, a conceded finding is never open), and the step is **never skipped by judgment** —
  if an input looks wrong, fix the input (dismiss the finding) and run the script, which is
  idempotent and safe. Also refreshed the step's stale doc lines (passed-status default is
  `Ready To Test`; ticket detection order is target.json → `BITBUCKET_BRANCH` → git branch).
  Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.53.2 / code-fixer 1.49.2 — 2026-08-05

### Fixed
- **Jira sync log now self-diagnoses a no-Jira-access token.** Jira answers **404** (hiding
  the issue) when the token authenticates but has no Jira access — exactly what happens when
  the sync falls back to a Pull-requests-scoped `BITBUCKET_API_TOKEN`. The skip line now says
  so and names the fix (`JIRA_API_TOKEN` with `read:jira-work` + `write:jira-work`) instead of
  a bare "HTTP 404" on a card that plainly exists. Diagnosed live: B20-11777 / B20-11716 sat
  eligible in Code Review with both transitions available while the sync skipped on this.
  Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.53.1 / code-fixer 1.49.1 — 2026-08-05

### Fixed
- **Jira sync now detects the ticket in CI (`update_card_status.py`).** In target mode
  (`--pr`/`--branch` — exactly what CI runs) the skill executes inside a **detached-HEAD
  worktree**, where `git branch --show-current` prints nothing — so ticket detection always
  failed and Step 10 soft-skipped with "No JIRA-style ticket detected", meaning the card
  never moved (observed live on B20-11777, which sat eligible in Code Review with both
  transitions available). Detection now tries, in order: `.ai-review/target.json` (the real
  branch in target mode) → `BITBUCKET_BRANCH` (provided by Pipelines) → the current git
  branch (local runs). Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.53.0 / code-fixer 1.49.0 — 2026-08-04

### Changed
- **Jira sync — board-flow rule.** `update_card_status.py` now implements "cards under
  review move by findings": open/unresolved findings → `Failed Code Review`; clean →
  **`Ready To Test`** (the passed-status default was `Code Review`, which parked clean cards
  back where they started). New guard: **only cards whose current status is in
  `JIRA_SOURCE_STATUSES`** (default `Code Review,Failed Code Review`) are transitioned — a
  card that is In Progress, already in QA, or Done is left alone. `Failed Code Review` is an
  eligible source deliberately, so a card that failed a previous run advances to
  `Ready To Test` when a re-run comes back clean. All three statuses remain overridable via
  env (`JIRA_FAILED_STATUS` / `JIRA_PASSED_STATUS` / `JIRA_SOURCE_STATUSES`). Reviewer-only
  (the fixer never touches Jira); `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.52.0 / code-fixer 1.48.0 — 2026-08-04

### Removed
- **Findings gate (`AI_REVIEW_FAIL_ON` / exit 3) removed from `ai-review-ci`** — reverting
  1.48.0. Blocking merges on a probabilistic reviewer contradicts the product's own stance
  (every comment is "a suggestion to verify, not a verdict"): one false 🔴 and a developer is
  stuck dismissing + re-running just to merge, and the Jira "Failed Code Review" sync already
  provides the process signal without a hard block. The wrapper is advisory again — exit codes
  are back to 0/1/2 only; a stale `AI_REVIEW_FAIL_ON` var is simply ignored. If a team later
  wants a gate once the reviewer's false-positive rate has earned it, restore from the 1.48.0
  commit. Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.51.0 / code-fixer 1.47.0 — 2026-08-03

### Changed
- **§4c Eloquent scopes is now the canonical rule, and it fires on readability, not just
  duplication.** Previously the "long chain → named scope" idea lived as a one-line bullet
  under §1c (repositories only) with no threshold, while §4c only caught *duplicated* chains —
  so a single unreadable 6-constraint chain in a Service or Job was never flagged. §4c now
  covers both triggers in any layer (🔵): a duplicated 2+ constraint chain, or a single chain of
  **4+ constraint calls** expressing one nameable business concept. Query construction
  (`select`/`with`/`orderBy`/`paginate`/…) never counts toward the threshold. Carve-outs:
  one-off report queries, chains already composed of scopes, and conditional request-filter
  chains. Includes BAD/GOOD examples and the placement discipline — the scope is defined on the
  Model, but the call site stays in the Repository (§1c). §1c and §5 bullets now cross-reference
  §4c. Shared-lens change — both skills.

### Changed
- **Model guard now allows Opus as well as Sonnet.** 1.49.0 shipped the guard as Sonnet-only,
  which stopped runs on Opus — too strict. The allowed set is now **Sonnet or Opus**; Fable,
  Haiku, and anything else still stop with
  `ERROR: <skill> only runs on Sonnet or Opus. Run /model sonnet and re-invoke this skill.`
  `ai-review-ci` accepts `AI_REVIEW_MODEL=opus` alongside the `sonnet` default and still fails
  pre-flight (exit 1) on anything else.
- **Fan-out slice agents stay pinned to Sonnet** even when the session is Opus. Rationale is now
  stated in the skill: a six-way fan-out on Opus is a lot of spend for mechanical lens
  application, and the judgment happens in the main context at arbitration. `fable`/`haiku` are
  never valid for a slice agent.

## code-reviewer 1.49.0 / code-fixer 1.45.0 — 2026-07-31

### Added
- **Sonnet-only model guard.** Both skills now check which model they are running as before
  anything else — before OS detection, before scoping the diff, before reading a file. On any
  model other than Sonnet (Fable, Opus, Haiku, …) the skill prints
  `ERROR: <skill> only runs on Sonnet. Run /model sonnet and re-invoke this skill.` and ends the
  turn. The guard explicitly forbids the obvious workaround — delegating the review to a Sonnet
  subagent — because arbitration (reviewer Step 8 / fixer Step 7) runs in the main context and
  must itself be Sonnet.

### Changed
- **Fan-out slice agents are pinned to Sonnet.** The six parallel lens-slice subagents
  (reviewer 7b / fixer 6b) must now be spawned with `model: sonnet` explicitly rather than
  inheriting the session model, and never on `fable`. Previously a slice agent silently
  inherited whatever the parent session was running.
- **`ai-review-ci` defaults `AI_REVIEW_MODEL` to `sonnet`.** The wrapper previously passed
  `--model` only when the var was set, letting CI inherit the CLI default — which the new guard
  would refuse, aborting the run after the container had spun up. It now defaults to `sonnet`
  and fails **pre-flight** (exit 1) on a non-sonnet override rather than dying at the guard
  mid-run. The banner always prints the effective model.

> **Note:** requiring Sonnet is a new precondition on invocation. Runs previously started under
> Opus (or any non-Sonnet model) will now stop at the guard.

## code-reviewer 1.48.0 / code-fixer 1.44.0 — 2026-07-30

### Added
- **Findings gate — fail the pipeline on open findings (`AI_REVIEW_FAIL_ON`).** New
  `ai-review-ci` env: `none` (default, advisory as before) | `critical` (🔴 only) |
  `warning` (🔴/🟡) | `any`. When the completed run leaves findings at/above the threshold —
  counting both findings posted this run (`findings.json`) and still-open findings from prior
  runs (`posted.json`, `resolved: false`; dismissed never count) — the wrapper exits **3**,
  distinct from infra (1) and run-error (2), so a pipeline can fail on findings while keeping
  API/infra hiccups advisory. Unknown/legacy severities count as 🔵 and can never trip a
  critical/warning gate. Banner prints the active gate. Reviewer-only; `code-fixer` bumps in
  lockstep, behaviour unchanged.

## code-reviewer 1.47.1 / code-fixer 1.43.1 — 2026-07-30

### Fixed
- **`ai-review-ci` no longer applies a USD budget cap to subscription-auth runs by default.**
  With `CLAUDE_CODE_OAUTH_TOKEN` (Pro/Max) there is no dollar bill — the CLI still tracks a
  USD-equivalent and `--max-budget-usd` killed a real HQ run mid-analysis at its cap, wasting
  the tokens and posting nothing. Now: an explicit `AI_REVIEW_MAX_USD` always wins; otherwise
  API-key runs default to 2.00 and OAuth runs are uncapped (the subscription quota is the
  limiter). Banner prints the effective budget. Also raised the "don't set below" guidance to
  ~2.00 — a full run on a large project (big skill + company CLAUDE.md context) measures
  ~$2–3-equivalent. Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.47.0 / code-fixer 1.43.0 — 2026-07-30

### Changed
- **§2a `declare(strict_types=1)` — enforce when applicable.** Previously flagged only on
  *new* `app/` files. Now an edited legacy `app/` file counts too when the diff meaningfully
  changes its logic (convention: *add when touching*), still 🔵. Judgment guards: a trivial
  touch (one-line unrelated fix, rename ripple, formatting) is NOT flagged — demanding a
  semantics-affecting declaration on a barely-touched file is scope creep — and the finding
  must be phrased with the risk in view: `strict_types` changes coercion semantics for the
  whole file, so suggest it alongside verifying the file's untouched paths (tests / call
  sites), never as a blind one-liner. Migrations/config/routes stay out of scope. Shared-lens
  change — both skills.

## code-reviewer 1.46.5 / code-fixer 1.42.5 — 2026-07-30

### Added
- **`ai-review-ci` accepts subscription auth.** Pre-flight now passes with either
  `ANTHROPIC_API_KEY` (API billing) or `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`,
  Pro/Max subscription); the banner names which auth is in use. Subscription tokens draw from
  that person's quota — fine for trials, prefer the API key for shared team pipelines.
  Reviewer-only; `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.46.4 / code-fixer 1.42.4 — 2026-07-29

### Changed
- **`ai-review-ci` default spend cap lowered 5.00 → 2.00 USD.** The cap is a runaway
  ceiling, not a target — runs bill actual usage; 2.00 covers the worst realistic
  sonnet fan-out with headroom. Docs now warn against setting it below ~1.00 (a run
  killed mid-review bills the tokens already spent but posts nothing) and point at
  `AI_REVIEW_MODEL=sonnet` as the real cost lever. Reviewer-only; `code-fixer`
  bumps in lockstep, behaviour unchanged.

## code-reviewer 1.46.3 / code-fixer 1.42.3 — 2026-07-29

### Fixed
- **CI headless runs work as root (`ai-review-ci`).** 1.46.2's `bypassPermissions` mode is
  hard-blocked when running as root ("cannot be used with root/sudo privileges", exit 1) —
  and Bitbucket Pipelines containers run as root, so the run died before starting. There is
  no sanctioned root override (verified against current docs: `--allow-dangerously-skip-permissions`
  only adds the mode to the interactive cycle; no env/settings escape). Reverted to
  `--permission-mode dontAsk` — root-compatible — and fixed the real 1.46.2-era bug: the
  allowlist used pattern-scoped entries (`Bash(git *)`, `Bash(bash */scripts/*)`) which never
  match the compound commands target mode actually runs (`cd "$WORKTREE" && "$SKILLS_ROOT/…"`),
  so every Bitbucket script was auto-denied. The allowlist now grants **unqualified** tool
  names (`Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Task`, `TodoWrite`) — all Bash
  calls allowed, appropriate for the ephemeral single-purpose CI container. Reviewer-only;
  `code-fixer` bumps in lockstep, behaviour unchanged.

## code-reviewer 1.46.2 / code-fixer 1.42.2 — 2026-07-29

### Fixed
- **CI headless runs can now post (`ai-review-ci` permission mode).** After the `--bare` fix
  the skill loaded and analysed the diff, but every Bitbucket-API script was denied and nothing
  posted. Cause: `--permission-mode dontAsk` **auto-denies** any tool not matched by the
  `--allowedTools` list — and the skill's `.sh` scripts run via an absolute `bash "$SKILLS_ROOT/…"`
  path (target mode) that the patterns didn't match, so `post_review.sh` never ran. Switched to
  `--permission-mode bypassPermissions`, the correct "run every tool without prompting" mode for
  an ephemeral CI container. Reviewer-only (`ai-review-ci`); `code-fixer` bumps in lockstep,
  behaviour unchanged.

## code-reviewer 1.46.1 / code-fixer 1.42.1 — 2026-07-29

### Fixed
- **CI headless runs now actually load the skill (`ai-review-ci`).** The wrapper invoked
  `claude --print "/code-reviewer" --bare`, but `--bare` does **not** load project skills — so
  `/code-reviewer` resolved to `Unknown command: /code-reviewer` and the run exited 0 with
  `num_turns: 0`, posting nothing (the pipeline's `|| true` then made it look green). Root-caused
  against CLI v2.1.220 by reproduction: without `--bare` the slash command resolves; with
  `--bare` it fails even in a trusted workspace. Fix: drop `--bare`. Auth still uses
  `ANTHROPIC_API_KEY` (no keychain/OAuth in a CI container). Also pre-accept workspace trust
  (`hasTrustDialogAccepted`) before invoking `claude` — `--print` skips the trust *dialog* but
  doesn't *grant* trust, and an untrusted workspace ignores settings permissions. Reviewer-only
  (`ai-review-ci` has no fixer counterpart); `code-fixer` bumps in lockstep per the shared-lens
  policy, behaviour unchanged.

## code-reviewer 1.46.0 / code-fixer 1.42.0 — 2026-07-29

### Added
- **Configurable base branch via `AI_REVIEW_BASE_BRANCH`.** Both skills previously hardcoded
  `origin/develop` as the diff base, so they only worked on repos with a `develop` integration
  branch. The base branch now resolves from `AI_REVIEW_BASE_BRANCH` (→ legacy `BASE_BRANCH` →
  `develop`), so a `master`-based (or any-based) repo works by setting one env var — e.g. in a
  Bitbucket Pipeline: `AI_REVIEW_BASE_BRANCH: master`.
  - Reviewer: the diff-base resolution (`BASE_REF`), `refresh_branch.sh`/`.ps1`, and
    `branch_summary.sh`/`.ps1` all honour it; `ai-review-ci` documents it and echoes it in the
    banner.
  - Fixer (mirrored per the shared-lens policy): the scoping diff commands in the template plus
    `branch_summary`, `pest_for_changed`, and `pint_changed` honour it.
  - `assets/bitbucket-pipelines.example.yml` and the README CI section document the knob; the
    example's `git fetch` uses `${AI_REVIEW_BASE_BRANCH:-develop}` so a non-develop repo only
    needs the repo variable set.

## code-reviewer 1.45.0 / code-fixer 1.41.0 — 2026-07-27

### Changed
- **§16f caching — frequency is now a first-class trigger.** The rule previously fired only
  on reads that were *both* expensive-per-call **and** frequent, which under-fired on a
  moderately-costed query sitting on a hot per-request path (the aggregate DB load is the
  problem even though no single call looks "expensive"). The trigger is now "served
  repeatedly **and** costs enough to be worth not repeating — expensive per call **or** cheap
  per call but on a hot path where the aggregate load adds up." The cheap-read carve-out is
  tightened to exclude only **trivial single-row indexed lookups** (`find($id)` on a PK),
  with an explicit note that **frequency alone doesn't justify caching a trivial lookup** —
  the Redis round-trip + staleness risk outweigh the saving. Net: catches the frequent-but-
  moderate read without spraming cache suggestions onto cheap PK lookups.

## code-reviewer 1.44.1 / code-fixer 1.40.1 — 2026-07-23

### Fixed
- **Checkpoint read no longer reports "no checkpoint" on a transient API error.**
  `get_checkpoint.sh` / `.ps1` used `curl -sSf` with no retry and treated *any* non-2xx or
  transport failure as "no checkpoint found" — so on a busy PR (many comment pages) a single
  429/5xx mid-pagination made the run fall back to a full-branch re-scan and read as if the
  saved checkpoint comment had vanished. Now transient failures (network, 429, 5xx) are
  retried with backoff, the fetch uses `pagelen=100` with a field filter to shrink pages, and
  a *persistent* API error exits with a distinct status (`3`) that prints a clear "couldn't
  read the checkpoint — API error; it likely still exists" warning instead of the misleading
  "no checkpoint" line. Genuine absence still falls back to a full review as before.
  Reviewer-only (checkpoint scripts have no fixer counterpart); `code-fixer` bumps in lockstep
  per the shared-lens versioning policy, behaviour unchanged.

## code-reviewer 1.44.0 / code-fixer 1.40.0 — 2026-07-23

### Changed
- **§2o Comments — broadened to catch narrating comments, not just line-level noise.** The
  rule now leads with *default to no comment* (clear names / small methods / early returns
  carry the meaning) and explicitly flags **step-label / section-divider** comments that
  announce a self-evident block (`// Build the payload`, `// Validate the request`, `// Save
  to the database`) — the most common form of comment noise — not only trivial line restatements
  like `$i++; // increment i`. When a block needs a label to be followable, the fix is to
  **extract a well-named method**, not to caption it. A `why` comment for genuinely non-obvious
  logic is still warranted; PHPDoc, tooling pragmas, and `TODO`/`FIXME`/`HACK` markers stay
  exempt. Shared-lens change, so both **code-reviewer** and **code-fixer** apply it (still
  🔵 Suggestion).

## code-reviewer 1.43.0 / code-fixer 1.39.0 — 2026-07-22

### Fixed
- **Reviewer no longer re-posts findings that are already on the PR.** Previously the
  posting path deduped only against *human* dismissals (`dismissals.json`) and in-thread
  resolutions — never against the skill's own machine-**resolved** comments. On a
  `--full-review` (which re-scans the whole diff) or when a later commit touched lines near
  a resolved finding, the detector re-fired and `post_review` posted a brand-new comment for
  something the developer had already fixed. Now:
  - `check_resolved.py` writes `.ai-review/posted.json` — an index of every AI finding
    already on the PR (open **and** resolved; dismissed ones stay owned by
    `check_dismissals.py`), each carrying `path` / `line` / `dim` / `severity` / `resolved`.
  - A new Step 8 filter skips any candidate matching a posted entry (same `path`, line within
    ±5, same `dim` — falling back to path+line for older comments with no `dim` marker). A
    still-open match would be a duplicate; a resolved match would resurrect a fixed finding.
    Not disabled by `--ignore-dismissals` (that flag is about human dismissals). A genuine
    regression is surfaced in the run summary rather than silently re-posted.

### Changed
- **`ai-review dismiss` now resolves the thread.** After writing the ❌ dismissed banner it
  POSTs to the comment's `/resolve` endpoint so the inline thread collapses in the Bitbucket
  UI — a dismissed finding is a closed conversation, same as a fixed one. Best-effort: the
  dismissal is already saved by the body update, so a resolve failure only leaves the thread
  visually open (`404`/`409` are treated as already-resolved / not-inline).

_Both changes are reviewer-only (resolved-comment tracking and dismissal plumbing are not
mirrored to the fixer, which already excludes resolved/dismissed findings from its work-list).
`code-fixer`'s version moves in lockstep per the shared-lens versioning policy; its behaviour
is unchanged._

## code-reviewer 1.42.0 / code-fixer 1.38.0 — 2026-07-20

### Reverted
- **Restored the §10 `report()`-over-`Log` rule to the shared lens** — reverting
  1.41.0/1.37.0, which had moved it out to the company `CLAUDE.md` scaffold. The soft
  🔵 Suggestion (prefer `report($e)` over `Log::error($e->getMessage())` for a
  locally-handled exception, and pass the exception not just its message if you do log) is
  back in the lens, along with the `log-getmessage` pre-scan rule in both `scan_diff.py`
  copies and its four tests. The mandate bullet added to `assets/CLAUDE.example.md` §5 is
  removed. The rule keeps its closing note that a team wanting to *mandate* one path can still
  encode that in its project `CLAUDE.md`. (Version bumped forward rather than back to keep the
  in-skill update check monotonic.)

## code-reviewer 1.40.0 / code-fixer 1.36.0 — 2026-07-17

### Added
- **§16f Cache hot, expensive reads in Redis** (🔵 Suggestion) — when the diff adds or reworks
  a read that is expensive to compute *and* served repeatedly with the same result (dashboard
  aggregates, reference/lookup data, expensive derived values, stable external API responses),
  suggest `Cache::remember()` backed by Redis. Hotness is judged from context — the card
  description / PR context, not just the code. A suggestion must name the three cache
  decisions (key parameters, TTL / staleness budget, invalidation path) and is suppressed for
  cheap reads, read-after-write-fresh data with no invalidation hook, unbounded key
  cardinality, rarely-hit paths, and already-cached values. Fix-first-cache-second: an
  underlying N+1 / full-table load stays the primary 🟡 finding.
- **§16g Files, images, and assets belong in S3, not on the server's disk** (🟡 Warning) —
  local-disk writes have repeatedly bloated app-server storage, and a file on one server is
  invisible to the others (and lost on redeploy/autoscale). Flags persistent writes to the
  `local`/`public` disk or under `public_path()`/`storage_path()`; recommends the company-wide
  S3-backed `Asset::storage()` helper as the idiomatic fix (or `Storage::disk('s3')`), with
  `temporaryUrl()` for private files. Legitimately-local **temp files** must live under
  `sys_get_temp_dir()` and carry failure-safe cleanup (`finally` + delete) — a temp file with
  no visible deletion is 🟡 on its own. Carve-outs: `Asset::storage()`/cloud-disk writes,
  default disk that may already be S3 (confirm, don't assert), framework-managed paths,
  ephemeral scratch with visible cleanup, `Storage::fake()` in tests. Complements §3e (upload
  validation), which stays canonical for type/size rules.
- **§11 Seeders over data migrations** — a **data-only migration** (rows written, no schema
  change) is 🟡 — data belongs in an idempotent seeder (`updateOrCreate()`/`upsert()` on a
  stable key); migrations stay schema-only. Exception: data that must run lock-step with a
  schema change in the same deploy (backfill before a non-null constraint) legitimately stays
  a migration. And a migration **altering a table another migration in the same branch
  created/modified** is 🔵 — fold it into the unreleased migration instead of stacking alters
  (never suggest editing an already-shipped migration).
- **§2d Route URIs → `kebab-case`** — new row in the naming-conventions table
  (`/user-profiles/{id}/payment-methods`); route URI casing previously had no rule.

## code-reviewer 1.28.0 / code-fixer 1.24.0 — 2026-07-06

### Added
- **§16 Scalability & Large Dataset Processing** — a new top-level review section applying
  an enterprise-scale lens (10M+ rows, millions of queued jobs, many concurrent workers
  across many servers, horizontal scaling) over data-touching changes. Deliberately
  **non-duplicative**: single-line smells already covered stay canonical elsewhere and §16
  just points at them (full-dataset loads & per-row writes → §9, N+1 → §4b, queue offload →
  §4e, transactions/races → §4g/§8). The section adds only the large-dataset / queued-workload
  rules that had no home:
  - **§16a `chunkById()` over `chunk()` on mutable tables** (🟡 Warning) — `chunk()`'s
    OFFSET pagination skips/duplicates rows under concurrent inserts/deletes or self-mutating
    loops; `chunkById()` keyset pagination is immune. §9's full-table-load bullet now points here.
  - **§16b Chunk-and-queue; avoid monolithic commands** (🔵 Suggestion) — separate
    orchestration from execution (discover → dispatch → process → aggregate → finalise);
    pass IDs/ID ranges, not serialised Eloquent collections; scale by adding workers.
  - **§16c Job idempotency** (🟡 Warning) — at-least-once delivery means jobs re-run; guard
    against duplicate rows/emails/charges with `updateOrCreate()` / `upsert()` / unique keys /
    dedupe markers.
  - **§16d Retry safety** (🔵 Suggestion) — small, independently-retryable units that don't
    lose committed progress on partial failure.
  - **§16e Concurrency under many workers** (🟡 Warning) — non-atomic read-modify-write races;
    recommend atomic DB ops, `lockForUpdate()` / optimistic locking, `ShouldBeUnique`,
    `Cache::lock()`, `Http::pool()` (extends §8).
- Rules live in the shared `src/review-lens.md` fragment, so both **code-reviewer** and
  **code-fixer** gain the section (code-fixer uses the same lens to know what to fix).

## code-reviewer 1.22.0 / code-fixer 1.18.0 — 2026-06-24

### Changed
- **Review recall — per-dimension coverage ledger + completeness critic.** Step 1 (Analyze)
  now walks the lens dimension by dimension, emits a printed coverage table (`§3 ✓ 1 finding ·
  §7 ✓ clean · §15 n/a — no Blade changed`), then does a focused second pass over every
  dimension cleared with zero findings. Converts "review the diff and mention what jumps out"
  into accountable, systematic coverage so rules aren't silently missed.

### Removed
- **Auto-fix command dropped from posted comments** (code-reviewer). Findings are now four
  sections (problem, AI fix prompt, suggested fix, why) — the trailing
  `ai-review fix --comment-id=…` line is gone, and the dead `{COMMENT_ID}` substitution was
  removed from `post_review.sh` / `.ps1`. The `ai-review fix` bin subcommand remains for
  manual use.

## code-reviewer 1.21.0 / code-fixer 1.17.0 — 2026-06-24

### Added
- **Discussion-decision check** in the card-context step — reads the ticket's comment thread
  (Atlassian MCP) and flags an implementation that contradicts or ignores a concrete technical
  decision raised there (🟡 Warning, confirm-not-accuse). Scoped to actionable steers; silent
  when the diff follows the decision or the thread already resolved it; skipped when comments
  aren't available.

## code-reviewer 1.20.0 / code-fixer 1.16.0 — 2026-06-24

### Added
- **§3i Hardcoded secrets and credentials** (🔴 Critical) — flags committed API keys, passwords,
  tokens, OAuth/client secrets, private keys, and DSNs with embedded passwords, by both
  secret-ish variable names and known key shapes (`sk_live_`, `AKIA`, `ghp_`, `xox*`, `AIza`,
  `-----BEGIN … PRIVATE KEY-----`, basic-auth URLs). Finding instructs to **rotate/revoke**, not
  just delete (it stays in git history). Exempts test/placeholder/public values.

### Changed
- De-bundled §3h: the old "hardcoded credentials **or** magic numbers" bullet split — magic
  literals now point to §2i, secrets get the dedicated §3i rule.

## code-reviewer 1.19.0 / code-fixer 1.15.0 — 2026-06-24

### Added
- **§2p extended — name must match behaviour** (🟡 Warning) — beyond requiring a verb, flags a
  method whose verb lies about what it does: a read-implying verb (`get`/`find`/`calculate`)
  that mutates, persists, deletes, or dispatches; a verb naming the wrong action; or a name
  hiding extra responsibilities. Read-the-body judgement guard; expected side effects exempt.

## code-reviewer 1.18.0 / code-fixer 1.14.0 — 2026-06-24

### Added
- **§2p Method names are verb phrases** (🔵 Suggestion) — flags action methods named as bare
  nouns (`totals()` → `calculateTotals()`). Exempts Eloquent relationships, accessors/
  attributes, boolean predicates (`is*`/`has*`/`can*`), query scopes, and framework-required
  names (`handle()`, `boot()`, `rules()`, `up()`/`down()`).

## code-fixer 1.13.1 — 2026-06-19

### Fixed
- **`check_version.ps1` (Windows)** — replaced a stray `⚠️` emoji on the out-of-date warning
  with ASCII `!!`, matching code-reviewer's convention that `.ps1` scripts stay pure ASCII
  (emoji corrupts to mojibake on a stock Windows console code page). The `.sh` twin keeps the
  emoji — it runs on UTF-8-clean Unix. This was the last emoji straggler in any fixer `.ps1`.

## code-reviewer 1.17.1 — 2026-06-19

### Changed
- **`post_review.sh` now accepts a UTF-8 findings-file path as its first argument**
  (`post_review.sh .ai-review/findings.json`), matching `post_review.ps1`; stdin remains a
  fallback. The two scripts are functional twins again.
- **Posting the review** now writes findings to `.ai-review/findings.json` and passes the path
  on *both* platforms instead of piping a here-string. This actually exercises the Windows
  emoji/em-dash mojibake fix shipped in 1.17.0 (the old Windows instructions still piped, so
  the fix was inert), and gives both platforms one identical calling convention.

## code-reviewer 1.17.0 / code-fixer 1.13.0 — 2026-06-19

### Added
- **§2n Descriptive, meaningful names** (🟡 Warning) — catches correctly-cased but opaque
  identifiers that §2d's casing table doesn't: cryptic vars (`$d`, `$tmp`), vague placeholders
  (`$data`, `$val`, `$thing`), unclear abbreviations (`$usrRepo`), and vague method names
  (`process()`, `getData()`, `doStuff()`). Exempts conventional short names (`$i`/`$j`/`$k`,
  `$e`, `$q`), well-known acronyms (`$url`, `$id`, `$dto`, `$pdf`), and framework-required
  method names (`handle()`, `boot()`, migration `up()`/`down()`, `rules()`/`authorize()`,
  Eloquent relationship methods).
- **§2o Comments — only where the code can't explain itself** (🔵 Suggestion) — flags
  redundant comments that restate the code, commented-out dead code left in the diff, and
  genuinely dense logic with no *why* comment. Exempts informative PHPDoc (generics / array
  shapes, `@throws`, `@deprecated`), tooling pragmas (`@phpstan-ignore`, `phpcs:ignore`,
  `@noinspection`), `TODO`/`FIXME`/`HACK` markers, and licence headers.

### Fixed
- **`post_review.ps1` (Windows)** now accepts a UTF-8 findings-file path as its first argument
  (`pwsh post_review.ps1 .ai-review/findings.json`), sidestepping the console code page, pipe
  encoding, and PowerShell's BOM-less here-string decoding — every boundary that could turn
  emoji / em-dashes into mojibake. The stdin here-string form still works as a fallback.

## code-reviewer 1.16.0 / code-fixer 1.12.0 — 2026-06-17

### Added
- **Task-relatedness file check** in the card-context step — flags changed files that fall
  outside the linked card's stated scope (🟡 Warning, judgement-scoped).

## code-reviewer 1.15.0 / code-fixer 1.11.0 — 2026-06-17

### Added
- **§2f–§2m readability rules** (all 🔵 Suggestion) — redundant `else` after `return` (§2f),
  guard clauses over deep nesting (§2g), nested ternaries (§2h), magic numbers / strings (§2i),
  boolean flag arguments (§2j), long parameter lists (§2k), double negatives (§2l), and
  `count()` for emptiness checks (§2m).

## code-reviewer 1.14.0 / code-fixer 1.10.0 — 2026-06-17

### Added
- **§2e Positive conditionals** (🔵 Suggestion) — an `if` with an `else` should test the
  positive case, not a negation; guard clauses / early returns with no `else` are exempt.

## code-reviewer 1.13.0 / code-fixer 1.9.0 — 2026-06-15

### Removed
- Deleted the 10 orphaned `references/*.md` files (5 × both skills) — never loaded by any
  SKILL.md or script; pure duplication of the lens. Dropped the dead "Reference material"
  footer from both skills.
- Removed dead `pest_for_changed.sh` / `pint_changed.sh` copies from **code-reviewer** (it
  never runs Pint/Pest; the fixer keeps its own).

### Fixed
- **Branch-name URL encoding** — `quote(..., safe='')` everywhere a branch is spliced into a
  Bitbucket BBQL query (`post_review`, `find_pr_id`, `setup_target`, `get_checkpoint`,
  `save_reviewed_sha`, both bins, `.ps1` twins). A `/` in a branch (e.g. `feature/B20-1`) no
  longer yields a false "no open PR found".
- `bb_put` now surfaces 401/403 via the shared `_maybe_warn_auth` helper instead of collapsing
  all errors to a bare bool; `bb_post_status` warns too.
- `cleanup_target` runs `git worktree prune` after the `rm -rf` fallback so no stale worktree
  entry leaks (`.sh` + `.ps1`).
- `pest_for_changed.sh` / `pint_changed.sh` no longer use `mapfile` / `declare -A` (bash 4+);
  rewritten portably so they work on macOS's stock bash 3.2.
- `scan_diff.py`: removed the flooding `resource-missing-when-loaded` pre-pass rule and
  downgraded `command-business-logic` from MUST to WARN (guard clauses are legitimate).

### Changed
- **CI headless allowlist** (`ai-review-ci`) now matches absolute-path / `bash …` / `python3 …`
  invocations used in target (`--pr`) mode, so worktree scripts aren't silently blocked under
  `--permission-mode dontAsk`.
- Installer writes `python3` (and Windows `pwsh`/`python`) tool patterns for both skills — the
  scripts call `python3` directly, which the old `python`-only allowlist missed.
- Packaging: `assets/` added to the npm `files` whitelist (the company-rules scaffold shipped
  empty before); `.npmignore` excludes `__pycache__`, `*.pyc`, and `*.template.md`.
- `.gitignore` now covers `.idea/` and `.claude/settings.local.json` (defense-in-depth).
- Docs corrected from "14-dimension" to **15** (Blade added); README gains a CI / headless
  (preview) section; this CHANGELOG backfilled to current versions.

### Added
- Test coverage for `aggregate_stats.py` (`classify`, `parse_meta`, `parse_created_at`) and
  `post_reply.py` marker logic.

## code-reviewer 1.12.0 — 2026-06-12

### Added
- **CI / headless mode** — `AI_REVIEW_CI=1` makes the skill skip every interactive prompt;
  new `bin/ai-review-ci` wrapper drives `claude --print --bare` for pipeline use.

### Changed
- Dropped the stray `(plain English)` / `(conditional)` parentheticals from posted-comment
  headings (also code-fixer 1.8.2).

## code-reviewer 1.11.0 — 2026-06-11

### Added
- **Jira card status sync** — after each run, transition the linked card to `Failed Code
  Review` (findings remain) or `Code Review` (clean / all-addressed) via direct Jira REST.
  New `update_card_status.py`; soft-skips when Jira env vars are absent.

## code-reviewer 1.10.0 / code-fixer 1.8.0 — 2026-06-09

### Added
- **Private end-of-run learning summary** — printed to the terminal and appended to the
  gitignored `.ai-review/learning-log.md` so the author keeps their reviewing instincts sharp.

## code-reviewer 1.9.1 / code-fixer 1.7.1 — 2026-06-08

### Changed
- Broadened §4b's manual-FK N+1 rule to be model-agnostic with varied parent/child examples.

## code-reviewer 1.9.0 / code-fixer 1.7.0 — 2026-06-08

### Added
- §4b now flags manual cross-table queries (`Model::find($fk)`) as N+1-shaped, not just
  relation access inside loops.

## code-reviewer 1.8.2 / code-fixer 1.6.1 — 2026-06-05

### Changed
- Aligned code-fixer with code-reviewer: card context loading, the "show the run" narration
  paragraph, `check_version` output, `.ps1` parity, and the "no blame author" rule.

## code-reviewer 1.8.1 — 2026-06-04

### Changed
- Every step script prints visible `🔍 / ✓ / ↷` progress instead of running silently.

## code-reviewer 1.8.0 — 2026-06-04

### Added
- **Load card context** (Step 0.2) — fetch the linked Jira card before analysis so the review
  judges whether the change solves the right problem. Status-aware `bb_post_status`.

## code-reviewer 1.7.1 — 2026-06-03

### Added
- When a finding is addressed, the inline thread is natively resolved in the Bitbucket UI.

## code-reviewer 1.7.0 / code-fixer 1.5.0 — 2026-06-03

### Added
- **Repository granularity** rule — one Repository per aggregate root (🔵 for splitting a
  child model out; 🟡 for a Service/Controller bypassing the parent Repository).

## code-reviewer 1.6.1 / code-fixer 1.4.1 — 2026-06-03

### Changed
- Bumped `whenLoaded` / `DB::transaction` / `Http::timeout` to 🟡 Warning; consolidated
  duplicate rules to canonical entries.

## code-reviewer 1.6.0 / code-fixer 1.4.0 — 2026-06-03

### Added
- **Dimension 15 — Blade views** (business logic in views, N+1 in `@foreach`, URL/attr XSS,
  CSRF, dynamic `@include`).

## code-reviewer 1.5.0 — 2026-06-02

### Added
- **Respond to developer replies on PR comments.** When a developer replies to one of the
  reviewer's findings — to push back, ask a question, or say they've fixed it — the next
  `/code-reviewer` run reads the thread and responds:
  - **Push-back it agrees with** → replies conceding and dismisses the finding so it isn't re-flagged.
  - **Push-back it disagrees with** → replies explaining why the finding still stands.
  - **A question** → answers inline.
  - **"I fixed it"** → verifies against the current code and, if genuinely addressed, replies and marks the finding resolved.

  Drafted replies are shown for confirmation before anything is posted.
- New `check_replies.py` (finds open findings whose thread ends with an unanswered developer
  reply; bot-vs-human is detected by the hidden `ai-review:` markers, not by account, since
  bring-your-own-key means the two can share a Bitbucket account) and `post_reply.py` (posts a
  threaded reply tagged with an anti-loop marker). Adds `bb_post()` to `_bitbucket.py`.

### Changed
- The "no new commits to review" early-exit now still runs the reply step first, so a manual
  re-run answers developer replies even when there is nothing new to review.

> Replies are answered on the next review run, not in real time — a reply doesn't trigger a
> build. Live, reply-time responses will arrive with the hosted version.

## code-reviewer 1.4.1 — 2026-06-01

### Fixed
- UTF-8 mojibake in the Windows PowerShell scripts.

## code-reviewer 1.4.0 — 2026-06-01

### Added
- Native Windows (PowerShell) support — the skill auto-detects the OS and runs the matching
  `.sh`/`.ps1` script variants.

## code-fixer 1.3.0 — 2026-05-29

### Added
- Windows compatibility and soft-dependency fallbacks.

## code-reviewer 1.2.4 — 2026-05-28

### Changed
- The AI disclaimer header is now script-owned (`post_review.sh`); the agent no longer posts it.

## code-reviewer 1.2.3 — 2026-05-28

### Fixed
- Dedupe the AI disclaimer header so it is posted once per PR.

## code-reviewer 1.2.2 — 2026-05-28

### Changed
- Clearer "checkpoint == HEAD" message and an early exit when there are no new commits.

---

Older history predates this changelog — see `git log`.
