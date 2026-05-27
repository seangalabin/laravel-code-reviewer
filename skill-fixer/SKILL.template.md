---
name: code-fixer
description: Diff-scoped code review and interactive fix applicator for the current branch. Reviews ONLY lines changed since develop, then walks you through applying fixes locally. No Bitbucket posting.
---

# Code Fixer

Reviews the **current branch's changes** against the base branch (`develop` for this repo). Findings must be anchored to lines that the branch actually changed — not to pre-existing code in untouched files.

---

## Step -1 — Version check (always first, before anything else)

```bash
.claude/skills/code-fixer/scripts/check_version.sh
```

- Exit **0** → continue normally.
- Exit **1** → stop immediately. Print the script's output as-is and do not proceed. The developer must update before running the skill.

---

## Global constraints

These apply in all modes and cannot be overridden by project config:

- **Never auto-commit.** Apply or post findings only — never run `git commit`, `git push`, or any destructive git operation.
- **Refuse on protected branches.** If the current branch is `main`, `master`, or `develop`, stop immediately: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`

---

## Step 0 — Check for project-specific overrides (optional)

If the project happens to have any of these files in the root, read them first and let them override the defaults in this skill:

- `CLAUDE.md` — project conventions for Claude Code
- `.coderabbit.yaml` — CodeRabbit review rules (if present)
- `.cursorrules` or `.github/copilot-instructions.md` — other agent rules

If none exist, skip this step. The skill's built-in rules are reasonable Laravel defaults and work standalone.

---

## Scope rule (read this before touching files)

**Review only what the branch changed.** That means:

- Added or modified lines in the diff — fair game, always.
- Deleted lines — fair game if the deletion introduces a regression or removes a guard.
- Pre-existing lines **inside a touched hunk** — fair game when the surrounding change makes them newly relevant.
- Pre-existing lines **outside any hunk, in a file the branch did not touch** — out of scope. Do not surface.
- Files the branch did not touch — out of scope. Do not open them looking for issues.

When a pre-existing issue is in a touched hunk, label it `(pre-existing, but touched)`.

**Do not flag issues already caught by Pint (formatting/style) or the Pest ArchitectureTest (suffix rules, base-class rules, enum rules).** Those run in CI before the card reaches code review.

### Honor inline suppression markers

Developers can suppress a finding by placing a marker on the 1–2 lines immediately above the offending line. A non-empty reason is required.

| Language | Marker |
|---|---|
| PHP / JS / Vue `<script>` | `// ai-review:ignore <reason>` |
| Blade | `{{-- ai-review:ignore <reason> --}}` |
| Vue `<template>` / HTML | `<!-- ai-review:ignore <reason> -->` |

When you encounter one of these markers above a line you would otherwise flag, **skip the finding**. The scan_diff.py pre-pass already honors these — apply the same rule to anything you would flag yourself. Empty reasons do not count as a valid suppression — flag those as a 🔵 Suggestion ("ignore marker missing reason").

---

## Scoping the review

Run these up-front to anchor the review:

```bash
.claude/skills/code-fixer/scripts/branch_summary.sh    # what changed: file counts, commits, base ref
.claude/skills/code-fixer/scripts/scan_diff.py         # pre-pass: pattern matches for mechanical red flags
```

Then read the full diff:

```bash
git diff origin/develop...HEAD    # source of truth for scope
```

`scan_diff.py` is a *pre-pass*, not a verdict. False positives are expected — read context and filter.

---

## Workflow

### Step 1 — Analyze

1. **Load project rules** (Step 0 above).
2. **Refuse if on a protected branch.** Run `git branch --show-current`. If it returns `main`, `master`, or `develop`, stop: `ERROR: Refusing to run on a protected branch. Check out your feature branch first.`
3. **Diff first.** Run the scoping scripts and read every hunk. Do not start by reading whole files.
4. **Read for context, not findings.** When a hunk references a Repository, Service, or Vuex store not in the diff, read the relevant part to understand intent — findings on those files are out of scope unless changed.
5. **Apply the full review lens** (all sections below) to everything in the diff.
6. **Compile all findings** grouped by severity (🔴 Critical → 🟡 Warning → 🔵 Suggestion). Do not modify any files yet.

Print a brief summary once analysis is done:

> Found **{N} issues** ({X} critical, {Y} warnings, {Z} suggestions). Starting fix loop.

### Step 2 — Pre-flight checks

Run these before touching any file:

1. Refuse if branch is `main`, `master`, or `develop` (already caught in Step 1).
2. Run `git status --short`. If the working tree has uncommitted changes, ask:
   > Working tree has uncommitted changes. Apply fixes anyway? [y/N]
   Default is **no** — stop unless the user explicitly types `y`.
3. Count files affected by the planned fixes. If more than 20 and `--force` was not passed, list the files and stop:
   > {N} files would be modified, which exceeds the 20-file limit per run. Narrow the scope or re-run with `--force`.

### Step 3 — Fix loop

Work through findings in Critical → Warning → Suggestion order.

For each issue:
1. Print the four-section issue (see Per-issue comment structure below).
2. Ask:
   > Apply this fix? [y/n/s/q]
   - `y` — apply the diff to the file, confirm with `✓ Fixed {file}:{line}`
   - `n` — skip this issue
   - `s` — skip all remaining issues of this severity level
   - `q` — quit the loop now, keep all fixes already applied

3. When `y` is chosen, apply the diff and append to `.ai-review/applied-{timestamp}.log`:
   ```
   File: {path}:{line}
   Prompt:
   {ai-fix-prompt text}

   Diff applied:
   {diff}
   ```

**End of loop — print summary:**

```
Applied {N} fix(es), skipped {M}.
Modified files:
  - {file1}
  - {file2}
Run your tests before pushing.
```

---

<!-- include:src/review-lens.md -->
## Output format

### Global rules

- **Plain language only.** Explain issues like you're talking to a junior dev on their first week. No jargon unless you immediately define it. Prefer "this runs the database query inside a loop, which is slow" over "N+1 query antipattern detected."
- **One issue per comment.** Do not bundle multiple problems into a single comment.
- **Be concrete.** Reference the actual variable, method, or line — not abstract concepts.

### Required opening message

🔧 **Code Fixer — review your changes are correct before committing**

### Per-issue comment structure

Each issue must contain these four sections, in this exact order, with these exact headings:

#### 1. The problem (plain English)
One or two sentences. What's wrong, in the simplest words possible. No "consider refactoring" — say what's actually broken or risky and why it matters.

#### 2. AI fix prompt
A complete, copy-pasteable prompt the developer can hand to Claude Code (or any AI assistant) to fix this. It MUST include:
- File path (e.g. `app/Services/OrderService.php`)
- Line number or method name
- The exact problem in one sentence
- Relevant surrounding context (what the method does, what calls it, what the constraint is)
- Acceptance criteria for the fix

Wrap it in a fenced code block labeled ` ```prompt ` so it's easy to copy.

Example:
```prompt
In `app/Services/OrderService.php`, method `calculateTotals()` (around line 47):
The method queries the database inside a foreach loop, causing one query per order item.
This service is called on every checkout, so it scales badly under load.
Refactor it to load all related items in a single query before the loop.
Keep the existing return type and method signature. Do not change the public API.
Follow HQ's Controller → DTO → Service → Repository layering — the query belongs in the repository, not the service.
```

#### 3. Suggested fix (code)
Show the actual code change. Use a diff-style block when possible:

```diff
- foreach ($orders as $order) {
-     $items = OrderItem::where('order_id', $order->id)->get();
- }
+ $items = $this->orderItemRepository->findByOrderIds($orders->pluck('id'));
```

If a diff doesn't fit (e.g. new file), show the full replacement code block with the language tag.

#### 4. Why this fix
Two or three sentences. Explain *why* this fix works, not just *what* it does. Connect it to a concrete consequence (performance, security, readability, layering rule).

### Severity tagging

Prefix each comment's title with one of:
- 🔴 **Critical** — bug, security issue, data loss risk. Creates a blocking task.
- 🟡 **Warning** — likely problem, performance, maintainability. Non-blocking.
- 🔵 **Suggestion** — style, readability, minor improvement. Optional.

---

## What not to do

- Don't comment on style issues already caught by the linter (Pint, ESLint).
- Don't open untouched files to look for new issues.
- Don't grade the whole architecture from a small change.
- Don't restate `.coderabbit.yaml` rules verbatim if the project uses CodeRabbit — it already does that on the PR.
- Don't flag issues caught by Pint or the Pest ArchitectureTest.
- Don't invent issues to fill buckets. An empty 🔴/🟡 list is a valid and welcome outcome.
- Don't run Pint, Pest, or ESLint — CI runs these before the card moves to code review.
- Don't suggest rewrites of working code unless there's a concrete reason.
- Don't say "consider" or "you might want to" — be direct: "this will fail when X" or "this is fine, but Y is faster."
- Don't repeat the same issue across multiple lines. Comment once on the first occurrence and mention "same pattern appears at lines X, Y, Z."
- Don't auto-commit, push, or stage any files. Ever.

---

## Scripts

- **`branch_summary.sh [base]`** — one-glance overview of what changed vs `origin/develop`.
- **`scan_diff.py [--base REF] [--no-snippets]`** — pre-pass pattern scanner. Only scans `+` lines. False positives filtered by the agent.

---

## Reference material

- `.claude/skills/code-fixer/references/laravel_review_guide.md` — Laravel-specific patterns, anti-patterns, correctness traps
- `.claude/skills/code-fixer/references/vue_review_guide.md` — Vue 3 / Vuex 4 patterns and component quality checks
- `.claude/skills/code-fixer/references/coding_standards.md` — PSR-12, naming conventions, method length limits
- `.claude/skills/code-fixer/references/common_antipatterns.md` — copy-paste reference for the most common violations
- `.claude/skills/code-fixer/references/code_review_checklist.md` — quick checklist for every diff
