#!/usr/bin/env python3
"""
run.py — score the review lens against labelled fixtures.

Why this exists: before this harness, nothing measured whether the reviewer finds
what it should or stays quiet when it should. 140+ commits of lens tuning shipped on
intuition, which means a rule tightened to kill one false positive could silently
kill true positives with no signal at all. This turns "the lens feels better" into a
number that can regress a build.

A case is two file trees and a label:

    evals/cases/010-n-plus-one-in-loop/
        base/app/Services/OrderService.php     # the base branch
        head/app/Services/OrderService.php     # the feature branch
        expect.json

    expect.json = {
      "description": "...",
      "must_fire":     [{"dim": "4b", "path": "app/Services/OrderService.php"}],
      "must_not_fire": ["2n", "13a"],
      "notes": "why this case exists"
    }

Trees rather than patches on purpose: a `.patch` rots against context lines and fails
to apply for reasons that have nothing to do with the lens. Two trees always apply.

Scoring, per dimension:
    recall    = must_fire entries the reviewer actually raised
    precision = raised findings that were expected (a must_not_fire hit is a false positive)

`must_not_fire` is the half that matters most and the half a naive harness omits. A lens
that flags everything scores perfect recall; the whole difficulty of review is silence.

    python3 evals/run.py --list
    python3 evals/run.py                          # full sweep
    python3 evals/run.py --case 010               # one case
    python3 evals/run.py --baseline evals/baseline.json   # fail on regression

COST: each case invokes the real skill, so a sweep costs real money. Cases are kept
tiny (10-30 changed lines) to hold that down, but this is a pre-release gate, not a
per-commit one. Tier 1 (free) lives in tests/test_scripts.py::TestScanDiffHybridRules.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / 'cases'
BASE_BRANCH = 'main'


def log(msg: str = '') -> None:
    print(msg, file=sys.stderr, flush=True)


def run(cmd: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def discover(selector: str | None) -> list[Path]:
    if not CASES_DIR.is_dir():
        return []
    cases = sorted(d for d in CASES_DIR.iterdir()
                   if d.is_dir() and (d / 'expect.json').exists())
    if selector:
        cases = [c for c in cases if c.name.startswith(selector) or selector in c.name]
    return cases


def build_repo(case: Path, workdir: Path) -> None:
    """Materialise the case as a two-commit git repo on a feature branch."""
    run(['git', 'init', '-q', '-b', BASE_BRANCH, '.'], workdir)
    run(['git', 'config', 'user.email', 'evals@local'], workdir)
    run(['git', 'config', 'user.name', 'evals'], workdir)
    # A remote is never contacted (dry run), but several scripts parse its URL and
    # bail without one.
    run(['git', 'remote', 'add', 'origin',
         'git@bitbucket.org:evals/fixture.git'], workdir)

    base = case / 'base'
    if base.is_dir():
        shutil.copytree(base, workdir, dirs_exist_ok=True)
    else:
        (workdir / '.gitkeep').write_text('')
    run(['git', 'add', '-A'], workdir)
    run(['git', 'commit', '-q', '-m', 'base'], workdir)

    run(['git', 'checkout', '-q', '-b', 'feature/EVAL-1-fixture'], workdir)
    head = case / 'head'
    if not head.is_dir():
        raise SystemExit(f'{case.name}: missing head/ tree')
    # Files the head tree drops must be deleted, not left behind from base.
    for existing in list(workdir.rglob('*')):
        if '.git' in existing.parts or not existing.is_file():
            continue
        rel = existing.relative_to(workdir)
        if (base / rel).exists() and not (head / rel).exists():
            existing.unlink()
    shutil.copytree(head, workdir, dirs_exist_ok=True)
    run(['git', 'add', '-A'], workdir)
    run(['git', 'commit', '-q', '-m', 'change under review'], workdir)


def install_skill(workdir: Path) -> None:
    dest = workdir / '.claude' / 'skills' / 'code-reviewer'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / 'skill', dest,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.template.md'))
    for script in dest.rglob('*'):
        if script.suffix in ('.sh', '.py') or script.parent.name == 'bin':
            script.chmod(0o755)


def invoke(workdir: Path, model: str, timeout: int) -> tuple[int, str]:
    env = {
        **os.environ,
        # Dry run: findings.json is written, nothing is posted anywhere.
        'AI_REVIEW_DRY_RUN': '1',
        'AI_REVIEW_CI': '1',
        'AI_REVIEW_BASE_BRANCH': BASE_BRANCH,
        # Grade the LENS, not the gate: the gate is measured separately by unit tests,
        # and leaving the CI floor in place would suppress every suggestion body and
        # make recall on 🔵 rules look falsely terrible.
        'AI_REVIEW_MIN_SEVERITY': 'suggestion',
        'AI_REVIEW_MAX_SUGGESTIONS': '99',
        'AI_REVIEW_NO_PREFLIGHT': '1',
        # Dummy creds: the scripts require them to be present, and dry run means
        # they are never used against a real endpoint.
        'BITBUCKET_EMAIL': 'evals@local',
        'BITBUCKET_API_TOKEN': 'dry-run',
    }
    for jira in ('JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN'):
        env.pop(jira, None)

    proc = subprocess.run(
        ['claude', '--print', '/code-reviewer',
         '--no-session-persistence', '--output-format', 'json',
         '--permission-mode', 'dontAsk', '--model', model,
         '--allowedTools', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash', 'TodoWrite',
         '--disallowedTools', 'Task'],
        cwd=workdir, capture_output=True, text=True, env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout + proc.stderr


def read_findings(workdir: Path) -> tuple[list[dict], str | None]:
    """Return (findings, error). A MISSING file is an error, not an empty result.

    This distinction is the whole ballgame. The skill writes findings.json on every
    completed analysis — `[]` when the diff is clean. So no file means the run died
    before it finished, and scoring that as "raised nothing" would mark every
    silence case as a perfect pass and every must_fire case as a lens miss. A
    crashed harness would look like a well-behaved reviewer.
    """
    path = workdir / '.ai-review' / 'findings.json'
    if not path.exists():
        return [], ('no .ai-review/findings.json — the run did not complete its '
                    'analysis (a clean review still writes `[]`)')
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [], f'findings.json is not valid JSON: {e}'
    if not isinstance(data, list):
        return [], f'findings.json is {type(data).__name__}, expected a list'
    return data, None


def norm_dim(value: object) -> str:
    """'§4b' / '4B' / '4b.' -> '4b'."""
    return re.sub(r'[^0-9a-z]', '', str(value).lower())


def score(case: Path, findings: list[dict]) -> dict:
    expect = json.loads((case / 'expect.json').read_text())
    must_fire = expect.get('must_fire', [])
    must_not = {norm_dim(d) for d in expect.get('must_not_fire', [])}

    raised = [{'dim': norm_dim(f.get('dim')), 'path': f.get('path', ''),
               'line': f.get('line'), 'severity': f.get('severity', '')}
              for f in findings]
    raised_dims = {r['dim'] for r in raised}

    hits, misses = [], []
    for want in must_fire:
        wdim, wpath = norm_dim(want.get('dim')), want.get('path')
        match = [r for r in raised
                 if r['dim'] == wdim and (wpath is None or r['path'].endswith(wpath))]
        (hits if match else misses).append(want)

    false_positives = [r for r in raised if r['dim'] in must_not]
    expected_dims = {norm_dim(w.get('dim')) for w in must_fire}
    unexpected = [r for r in raised
                  if r['dim'] not in expected_dims and r['dim'] not in must_not]

    return {
        'case': case.name,
        'description': expect.get('description', ''),
        'recall': f'{len(hits)}/{len(must_fire)}' if must_fire else 'n/a',
        'recall_pct': (100 * len(hits) / len(must_fire)) if must_fire else None,
        'missed': misses,
        'false_positives': false_positives,
        'unexpected': unexpected,
        'raised': sorted(raised_dims),
        'passed': not misses and not false_positives,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', help='Run only cases whose name matches this.')
    ap.add_argument('--list', action='store_true', help='List cases and exit.')
    ap.add_argument('--model', default=os.environ.get('AI_REVIEW_MODEL', 'opus'))
    ap.add_argument('--timeout', type=int, default=900, help='Per-case seconds.')
    ap.add_argument('--report', default='evals/report.json')
    ap.add_argument('--baseline', help='Compare against a previous report; '
                                       'exit 1 if any dimension regressed.')
    ap.add_argument('--keep', action='store_true',
                    help='Keep the temp workdirs for debugging.')
    args = ap.parse_args()

    cases = discover(args.case)
    if not cases:
        log(f'No cases found in {CASES_DIR}.')
        return 1

    if args.list:
        for c in cases:
            e = json.loads((c / 'expect.json').read_text())
            fire = ', '.join(f'§{norm_dim(w["dim"])}' for w in e.get('must_fire', [])) or '—'
            quiet = ', '.join(f'§{norm_dim(d)}' for d in e.get('must_not_fire', [])) or '—'
            print(f'{c.name}\n    {e.get("description","")}\n'
                  f'    must fire: {fire}\n    must NOT fire: {quiet}')
        return 0

    if not shutil.which('claude'):
        log('ERROR: `claude` CLI not on PATH — the harness invokes the real skill.')
        return 1

    log(f'Running {len(cases)} case(s) on {args.model}.\n')
    results = []
    for i, case in enumerate(cases, 1):
        workdir = Path(tempfile.mkdtemp(prefix=f'eval-{case.name}-'))
        log(f'[{i}/{len(cases)}] {case.name}')
        try:
            build_repo(case, workdir)
            install_skill(workdir)
            rc, output = invoke(workdir, args.model, args.timeout)
            findings, read_error = read_findings(workdir)
            result = score(case, findings)
            result['exit_code'] = rc
            if read_error:
                # An incomplete run is never a pass, whatever the labels say.
                result['passed'] = False
                result['error'] = read_error
                result['run_output'] = output[-800:]
            results.append(result)
            if read_error:
                mark = 'ERROR'
            elif result['passed']:
                mark = 'PASS'
            else:
                mark = 'FAIL'
            log(f'      {mark}  recall {result["recall"]}  '
                f'raised {result["raised"] or "nothing"}')
            if read_error:
                log(f'        {read_error}')
                log(f'        exit={rc}  tail: {output[-200:].strip()}')
            for m in result['missed']:
                log(f'        MISSED  §{norm_dim(m["dim"])} {m.get("path","")}')
            for fp in result['false_positives']:
                log(f'        FALSE+  §{fp["dim"]} {fp["path"]}:{fp["line"]}')
        except subprocess.TimeoutExpired:
            results.append({'case': case.name, 'passed': False,
                            'error': f'timed out after {args.timeout}s'})
            log(f'      TIMEOUT after {args.timeout}s')
        finally:
            if args.keep:
                log(f'      workdir kept: {workdir}')
            else:
                shutil.rmtree(workdir, ignore_errors=True)

    # ── Per-dimension rollup ─────────────────────────────────────────────────
    per_dim: dict[str, dict] = {}
    for r in results:
        for m in r.get('missed', []):
            per_dim.setdefault(norm_dim(m['dim']), {'expected': 0, 'found': 0, 'false_pos': 0})['expected'] += 1
        for w in json.loads((CASES_DIR / r['case'] / 'expect.json').read_text()).get('must_fire', []) \
                if (CASES_DIR / r['case'] / 'expect.json').exists() else []:
            d = per_dim.setdefault(norm_dim(w['dim']), {'expected': 0, 'found': 0, 'false_pos': 0})
            if not any(norm_dim(m['dim']) == norm_dim(w['dim']) for m in r.get('missed', [])):
                d['found'] += 1
        for fp in r.get('false_positives', []):
            per_dim.setdefault(fp['dim'], {'expected': 0, 'found': 0, 'false_pos': 0})['false_pos'] += 1
    for d in per_dim.values():
        d['expected'] = max(d['expected'], d['found'])

    errored = sum(1 for r in results if r.get('error'))
    passed = sum(1 for r in results if r.get('passed'))
    report = {'model': args.model, 'cases': len(results),
              'passed': passed, 'failed': len(results) - passed - errored,
              'errored': errored,
              'per_dimension': per_dim, 'results': results}

    out = REPO_ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    log('\n' + '─' * 62)
    log(f'{passed}/{len(results)} case(s) passed on {args.model}'
        + (f'  ({errored} could not be scored)' if errored else ''))
    if errored:
        log('\nCases that ERRORED did not run to completion — their scores are not '
            'evidence about the lens either way. Fix those before reading the table.')
    if per_dim:
        log(f'\n{"dim":<8}{"recall":<12}{"false pos":<11}')
        for dim in sorted(per_dim):
            s = per_dim[dim]
            log(f'§{dim:<7}{s["found"]}/{s["expected"]:<10}{s["false_pos"]:<11}')
    log(f'\nreport: {out}')

    if args.baseline:
        base_path = REPO_ROOT / args.baseline
        if not base_path.exists():
            log(f'\nNo baseline at {base_path} — writing this run as the baseline.')
            base_path.write_text(json.dumps(report, indent=2))
        else:
            old = json.loads(base_path.read_text())
            regressions = []
            for dim, now in per_dim.items():
                was = old.get('per_dimension', {}).get(dim)
                if not was:
                    continue
                if now['found'] < was['found']:
                    regressions.append(f'§{dim} recall {was["found"]} -> {now["found"]}')
                if now['false_pos'] > was['false_pos']:
                    regressions.append(f'§{dim} false positives {was["false_pos"]} -> {now["false_pos"]}')
            if regressions:
                log('\nREGRESSED vs baseline:')
                for r in regressions:
                    log(f'  {r}')
                return 1
            log('\nNo regression vs baseline.')

    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
