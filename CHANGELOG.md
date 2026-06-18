# Changelog

This repo ships two independently-versioned skills — **code-reviewer** and **code-fixer**
(see [Versioning](README.md#versioning)). Each entry below is tagged with the skill it
applies to and its `VERSION` at that release. Versions follow [semver](https://semver.org/);
the format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
