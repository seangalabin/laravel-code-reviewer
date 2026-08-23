# Review-lens evals

Measures whether the reviewer **finds what it should** and — the harder half —
**stays quiet when it should**.

Before this existed, nothing measured review quality. The 150+ tests in
`tests/test_scripts.py` cover Bitbucket plumbing, build idempotency, and cost guards;
none of them touch the lens. That meant 140+ commits of lens tuning shipped on
intuition, and a rule tightened to remove one false positive could silently remove
true positives with no signal at all.

## Two tiers, because one of them costs money

| | What | Cost | When |
|---|---|---|---|
| **Tier 1** | `scan_diff.py` pattern rules, scored against inline diffs | free, milliseconds | every commit, via `tests/test_scripts.py::TestScanDiffHybridRules` |
| **Tier 2** | the **full lens**, scored by invoking the real skill | real money per case | before shipping a lens change |

Tier 1 is the regression net. Tier 2 is the thing that actually grades judgement, and
it is a **release gate, not a commit gate** — wire it into the release ritual, not the
pipeline.

## Running it

```bash
python3 evals/run.py --list                 # what cases exist, and what each asserts
python3 evals/run.py                        # full sweep (costs money)
python3 evals/run.py --case 040             # one case
python3 evals/run.py --model sonnet         # compare models on the same corpus
python3 evals/run.py --keep                 # leave temp workdirs for debugging
python3 evals/run.py --baseline evals/baseline.json   # exit 1 on regression
```

Every run is a **dry run** (`AI_REVIEW_DRY_RUN=1`): findings are written to
`.ai-review/findings.json` in a throwaway temp repo and nothing is ever posted to
Bitbucket or Jira. The harness also sets `AI_REVIEW_MIN_SEVERITY=suggestion` so it
grades the *lens*, not the severity gate — leaving the CI floor on would suppress every
suggestion body and make recall on 🔵 rules look falsely terrible.

## Writing a case

```
evals/cases/NNN-short-slug/
    base/          file tree at the base branch   (optional — omit for a new file)
    head/          file tree on the feature branch (required)
    expect.json
```

```json
{
  "description": "one line: what the diff does",
  "must_fire":     [{"dim": "4b", "path": "app/Repositories/OrderRepository.php"}],
  "must_not_fire": ["2n", "13a"],
  "notes": "why this case exists, and why each must_not_fire entry is listed"
}
```

Trees rather than `.patch` files on purpose: a patch rots against its context lines and
starts failing to apply for reasons that have nothing to do with the lens.

Three rules for a case that earns its keep:

1. **Keep it tiny.** 10–30 changed lines. Every case costs a real review; a large
   fixture buys no extra signal and multiplies the sweep cost.
2. **Always populate `must_not_fire`.** A lens that flags everything scores perfect
   recall. Silence is the difficult half, and a case with no `must_not_fire` does not
   test it. `030-clean-diff-stays-quiet` is the purest version: nothing at all should
   be raised.
3. **Say why in `notes`.** Six months on, the reason a dimension is on the quiet list
   is the only thing that stops someone "fixing" the case instead of the lens.

## Seed the corpus from real history, not imagination

`skill/scripts/mine_feedback.py` already classifies every finding the reviewer has ever
posted. Its two useful verdicts map straight onto the two halves of a case:

- **dismissed** — a human said "false positive" → a `must_not_fire` entry
- **resolved** — a human said "real, and I fixed it" → a `must_fire` entry

```bash
.claude/skills/code-reviewer/scripts/mine_feedback.py --prs 50
# then turn .ai-review/feedback-report.json into cases
```

Every future dismissal is a free regression test. That is the loop worth closing:
`LENS-TUNING.md` describes the ritual, this harness is what makes it measurable.

## Reading the output

```
dim     recall      false pos
§4b     3/3         0
§17a    1/2         0
§2n     0/0         2          <- fires where it shouldn't: tighten the carve-outs
```

`false pos` counts `must_not_fire` hits. A dimension with high recall **and** false
positives is not working — it is just loud.
