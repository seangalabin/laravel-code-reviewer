# Lens tuning — the learning loop

The reviewer only gets better when review outcomes flow back into the lens. Two triggers,
one workflow. Rule-writing follows one standard: **rules are generic decision procedures;
examples are boundary markers, never the originating incident retold.**

## Trigger 1 — scheduled mining (monthly, or every ~20 reviews)

1. In the target repo (needs `BITBUCKET_EMAIL` / `BITBUCKET_API_TOKEN`):

   ```bash
   .claude/skills/code-reviewer/scripts/mine_feedback.py --prs 30
   ```

   Writes `.ai-review/feedback-report.json`: every AI finding's lifecycle
   (resolved / dismissed+reason / open), grouped per dimension.

2. Open a Claude session in **this repo** and say:

   > Tune the lens from `<path>/.ai-review/feedback-report.json`

3. What the tuning session looks for:
   - **High dismissed ratio on a dimension** → the rule over-fires; write a carve-out from
     the recurring dismissal reasons.
   - **Recurring dismissal reason wording** → that sentence *is* the missing exemption.
   - **High resolved ratio** → the rule earns its keep; leave it alone.
   - **Dimensions that never fire** → dead weight or mis-scoped triggers; investigate before
     deleting.

4. Ship rule changes like any lens change: edit `src/review-lens.md`, `python3 build.py`,
   bump both VERSIONs, CHANGELOG entry citing the *pattern* (not one PR), push.

## Trigger 2 — escaped defect (per incident)

A bug reached staging/production from a reviewed PR:

1. Open a Claude session in this repo and say:

   > Postmortem: bug <JIRA-KEY> escaped review on PR #<N>. Which lens dimension should have
   > caught it? Propose the rule change.

2. Outcomes, in order of preference:
   - An existing rule *should* have fired but its trigger missed the shape → sharpen the
     trigger.
   - No rule covers the defect class → new rule (generic, with the incident abstracted away).
   - A rule fired and was wrongly dismissed → not a lens problem; feed Trigger 1.

3. Ship the same way as above.

## Guardrails

- Every proposal must pass the generic-rule standard before shipping (see the
  `feedback_lens_rules_generic` memory).
- One pattern, one rule change — don't batch unrelated tweaks into one bump.
- If an eval set exists (fixture PRs with seeded defects), re-run it after the change;
  recall drops = regression, fix before pushing.
