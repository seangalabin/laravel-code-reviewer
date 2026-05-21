---
name: code-reviewer
description: Diff-scoped code review for the current branch. Reviews ONLY the lines changed since the base branch (develop) — not entire files. Use when reviewing pull requests, providing feedback on uncommitted changes, or auditing a branch before merge.
---

# Code Reviewer

Reviews the **current branch's changes** against the base branch (`develop` for this repo, per `CLAUDE.md`). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

## Scope rule (read this first)

**Review only what the branch changed.** That means:

- Added or modified lines in the diff — fair game, always.
- Deleted lines — fair game if the deletion introduces a regression or removes a guard.
- Pre-existing lines **inside a touched hunk** — fair game when the surrounding change makes them newly relevant or when the rule the file violates is repo-wide and the file is already open.
- Pre-existing lines **outside any hunk, in a file the branch did not touch** — out of scope. Do not surface.
- Files the branch did not touch — out of scope. Do not open them looking for issues.

Reading surrounding context (the rest of the changed file, the called Repository, the consuming Vue store) is encouraged for *understanding* the change. Findings are still bounded by the rule above.

When a pre-existing issue is in a touched hunk, label it `(pre-existing, but touched)` so the author knows it isn't blamed on this branch.

## Scoping the review

Helper scripts in `scripts/` produce the canonical starting artefacts. Run them up-front so the rest of the review is anchored:

```bash
./scripts/branch_summary.sh             # what changed: file counts by type, commits, base ref
./scripts/scan_diff.py                  # pre-pass: pattern matches against .coderabbit.yaml red flags
./scripts/pint_changed.sh               # Pint --test on the changed PHP files only
./scripts/pest_for_changed.sh           # Pest for the 1:1 test files of changed app/ code
```

Then read the diff itself:

```bash
git diff origin/develop...HEAD          # the full diff — source of truth for scope
```

Use `origin/develop...HEAD` (three dots) — that diff is "everything the branch added since it forked from develop," which matches what reviewers see in the PR. Two-dot diff is misleading when develop has moved on.

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — the agent reads context and filters. Its job is to surface mechanical red-flag matches (direct Eloquent in a Controller, `dd()` left in, missing return types, console.log in Vue, etc.) so they aren't missed.

If the user gave a PR URL or ID, mention it; otherwise the local branch diff is the review surface.

## Workflow

1. **Diff first.** Look at every hunk. Do not start by reading whole files.
2. **Read for context, not for findings.** When a hunk references a Repository, Service, or store module that isn't in the diff, read the relevant part to understand the call — but findings on those external files are out of scope unless they were also changed.
3. **Run the project's gates if relevant to the change.** `vendor/bin/pint --test path/to/file.php` and `vendor/bin/pest path/to/test.php` for PHP changes. `npm run lint` for JS/Vue. Failing gates are blockers; mention them as such.
4. **Apply the rules from `CLAUDE.md` and `.coderabbit.yaml`.** Those files govern this repo. They override the generic checklists in `references/`. If a generic best practice in `references/` conflicts with `.coderabbit.yaml`, `.coderabbit.yaml` wins.
5. **Compile findings as a tight report** — file:line anchors, severity buckets, concrete suggestions (see Output format below). Store the full report text in a shell variable or temp file.
6. **Post findings as inline comments on the Bitbucket PR.** After compiling the review, build a JSON array and pipe it to `post_review.sh`. Each finding with a `path` + `line` is posted as an inline comment anchored to that file and line. An item with only `body` (no `path`/`line`) is posted as a top-level PR comment — use that for the compliance summary.

```bash
.claude/skills/code-reviewer/scripts/post_review.sh <<'FINDINGS'
[
  {
    "path": "app/Http/Controllers/TestimonialController.php",
    "line": 122,
    "body": "**MUST FIX** *(pre-existing, but touched)* — Direct `Testimonial::where(...)` Eloquent query inside a controller method; move to a `TestimonialRepository` method."
  },
  {
    "path": "resources/js/components/agents/AgentEditTestimonials.vue",
    "line": 258,
    "body": "**WARN** — `<style>` block is not scoped; `.sortable` and `.sort-btn` will leak into the global stylesheet. Change to `<style scoped>`."
  },
  {
    "body": "**Compliance summary**\n\n| Gate | Result |\n|---|---|\n| Pint | ✅ PASS |\n| Pest | ✅ PASS |\n| ESLint | ✅ PASS |\n\n**Verdict: not safe to merge as-is.** 1 MUST FIX blocks."
  }
]
FINDINGS
```

Use the line number from the diff (the `+` side) for each finding. The script infers workspace/repo from the git remote and finds the open PR for the current branch automatically. If it succeeds, include the returned PR URL in your response. If it fails (no open PR, missing credentials), show the review inline and note why posting was skipped — do not silently swallow the error.

## Output format

Group findings under two buckets that match the project's CodeRabbit setup:

- **MUST FIX** — blocks merge (violates an explicit `.coderabbit.yaml` MUST FIX rule, breaks a gate, introduces a security or data-integrity bug, or removes a guard).
- **WARN** — should be addressed but doesn't block (style drift, minor perf, pre-existing-but-touched issues, missing tests for a thin slice).

Each finding includes:
- A file:line anchor that matches a line *in the diff* (or the closest changed line if the issue spans a hunk).
- One sentence stating the problem.
- One sentence stating the fix (or a code snippet if it's short).
- The `(pre-existing, but touched)` tag when applicable.

End with a short compliance summary: Pint / Pest / lint status, plus a one-line "is this safe to merge" verdict for the user. Do not narrate the review process; the diff and the findings are the artefact.

## What not to do

- Don't open files outside the diff to look for new issues.
- Don't grade the whole architecture from a small change. A bug fix doesn't need a refactor.
- Don't restate `.coderabbit.yaml` rules verbatim — apply them. CodeRabbit will surface its own findings in the PR; the value here is the human-tier review on top.
- Don't claim test coverage from running `pest --filter` on a single file. The CI gate is the full suite; if the change touches code paths that other tests cover, say so explicitly.
- Don't invent issues to fill the buckets. An empty MUST FIX list is a valid outcome.

## Scripts

The `scripts/` directory contains five helpers tuned for this Laravel/Vue stack:

- **`branch_summary.sh [base]`** — one-glance overview of what the branch changed vs `origin/develop` (or the supplied base). Always-safe to run first.
- **`scan_diff.py [--base REF] [--no-snippets]`** — Python pre-pass. Parses the unified diff and flags red-flag patterns scoped by layer: Controller / Service / Repository / Vue / Blade. Only scans `+` lines (added or modified). False positives are filtered by the agent; the script's job is to make sure nothing mechanical slips by.
- **`pint_changed.sh [--fix]`** — runs Pint on only the changed PHP files. Default is `--test`; pass `--fix` to auto-format and stage.
- **`pest_for_changed.sh [extra pest args]`** — maps each changed `app/Foo/Bar.php` to `tests/Feature/Foo/BarTest.php` (per the project's `ArchitectureTest` convention) and runs only those. Skips the full suite, which is what CI runs anyway.
- **`post_review.sh`** — posts the compiled review as a comment on the open Bitbucket PR for the current branch. Reads the review from stdin. Requires two env vars to be set:
  - `BITBUCKET_EMAIL` — your Bitbucket account email (e.g. `sean@redhq.com.au`)
  - `BITBUCKET_API_TOKEN` — a Bitbucket API token with **Pull requests: write** scope (create one at <https://bitbucket.org/account/settings/personal-access-tokens/>)

All five exit cleanly with `0` on success; non-zero on failure. Designed to be cheap to run repeatedly during a review.

## Reference material (optional)

These files are generic cross-language reference, secondary to `CLAUDE.md` + `.coderabbit.yaml`:

- `references/code_review_checklist.md` — generic checklist patterns
- `references/coding_standards.md` — generic style notes
- `references/common_antipatterns.md` — generic anti-patterns

Defer to the project's own rules when they conflict.
