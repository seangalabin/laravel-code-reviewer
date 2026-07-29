# Changelog

This repo ships two independently-versioned skills — **code-reviewer** and **code-fixer**
(see [Versioning](README.md#versioning)). Each entry below is tagged with the skill it
applies to and its `VERSION` at that release. Versions follow [semver](https://semver.org/);
the format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
