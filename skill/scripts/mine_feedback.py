#!/usr/bin/env python3
"""
mine_feedback.py — mine reviewer-feedback signals from recent PRs.

Walks the most recently updated PRs (merged + open), extracts every AI
finding's lifecycle, and aggregates the signals the lens-tuning ritual needs:

  - resolved     — the finding led to a fix (the rule earned its keep)
  - dismissed    — a human said not-an-issue, with the reason they gave
                   (false-positive patterns live here)
  - open         — posted, not yet acted on

Output: `.ai-review/feedback-report.json` plus a per-dimension summary table
on stderr. Feed the JSON to a lens-tuning session — dimensions with a high
dismissed ratio need carve-outs; recurring dismissal reasons are rule edits
waiting to be written.

Usage:
    mine_feedback.py [--prs 30]

Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
Soft-exits (writing an empty report) when creds or the remote are missing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import bb_get, fetch_all_comments, get_creds, get_repo_info, repo_api_base

OPEN_RE      = re.compile(r'<!--\s*ai-review:open:([a-f0-9]+)\s*-->')
RESOLVED_RE  = re.compile(r'<!--\s*ai-review:resolved:([a-f0-9]+)\s*-->')
DISMISSED_RE = re.compile(r'<!--\s*ai-review:dismissed\s+(\{.*?\})\s*-->')
META_RE      = re.compile(r'<!--\s*ai-review:meta\s+(\{[^}]+\})\s*-->')


def classify_finding(body: str) -> tuple[str, dict] | None:
    """Return (state, meta) for an AI finding comment, or None for non-findings.

    state: 'resolved' | 'dismissed' | 'open'
    meta:  dim/severity from the meta marker; dismissals also carry 'reason'.
    """
    m = DISMISSED_RE.search(body)
    if m:
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            meta = {}
        return 'dismissed', meta
    meta = {}
    mm = META_RE.search(body)
    if mm:
        try:
            meta = json.loads(mm.group(1))
        except json.JSONDecodeError:
            meta = {}
    if RESOLVED_RE.search(body):
        return 'resolved', meta
    if OPEN_RE.search(body):
        return 'open', meta
    return None


def aggregate(findings: list[dict]) -> dict:
    """Group finding lifecycles into the per-dimension tuning summary."""
    dims: dict[str, dict] = {}
    for f in findings:
        dim = f.get('dim') or '?'
        row = dims.setdefault(dim, {
            'posted': 0, 'resolved': 0, 'dismissed': 0, 'open': 0,
            'dismissal_reasons': [],
        })
        row['posted'] += 1
        row[f['state']] += 1
        if f['state'] == 'dismissed' and f.get('reason'):
            row['dismissal_reasons'].append(f['reason'])
    return dims


def build_digest(findings: list[dict], dims: dict, prs: list[dict], window: str) -> str:
    """Email-ready plain-text digest of the mined findings."""
    lines = [
        f'AI code review — learning digest ({window})',
        '=' * 60,
        '',
        f'PRs with review activity: {len(prs)}',
        f'Findings touched: {len(findings)}',
        '',
        'Per dimension:',
        f'  {"Dim":<8}{"posted":>7}{"resolved":>10}{"dismissed":>11}{"open":>6}',
    ]
    for dim in sorted(dims):
        r = dims[dim]
        lines.append(f'  §{dim:<7}{r["posted"]:>7}{r["resolved"]:>10}'
                     f'{r["dismissed"]:>11}{r["open"]:>6}')
    reasons = [(d, why) for d, r in sorted(dims.items()) for why in r['dismissal_reasons']]
    if reasons:
        lines += ['', 'Dismissal reasons (each one is a candidate lens carve-out):']
        lines += [f'  - §{d}: {why}' for d, why in reasons]
    open_by_pr: dict[int, int] = {}
    for f in findings:
        if f['state'] == 'open':
            open_by_pr[f['pr']] = open_by_pr.get(f['pr'], 0) + 1
    if open_by_pr:
        lines += ['', 'Still-open findings by PR:']
        lines += [f'  - PR #{pr}: {n} open' for pr, n in sorted(open_by_pr.items())]
    lines += [
        '',
        'To act on this: open a Claude session in the skill repo and say',
        '"Tune the lens from .ai-review/feedback-report.json" (see LENS-TUNING.md).',
    ]
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prs', type=int, default=30,
                        help='How many most-recently-updated PRs to mine (default 30).')
    parser.add_argument('--since-hours', type=int, default=None,
                        help='Only mine PRs updated within the last N hours '
                             '(daily-digest mode: --since-hours 24).')
    parser.add_argument('--digest', default=None, metavar='FILE',
                        help='Also write an email-ready plain-text digest to FILE. '
                             'With --since-hours, the file is only written when there '
                             'is activity — exit code 3 signals "nothing to send".')
    args = parser.parse_args()

    out_path = Path('.ai-review/feedback-report.json')
    Path('.ai-review').mkdir(exist_ok=True)

    def soft_exit(msg: str) -> None:
        print(f'  ↷ {msg}', file=sys.stderr)
        out_path.write_text(json.dumps({'findings': [], 'dimensions': {}}, indent=2))
        sys.exit(0)

    window = f'PRs updated in the last {args.since_hours}h' if args.since_hours \
             else f'the last {args.prs} PRs'
    print(f'🔍 Mining reviewer feedback from {window}...', file=sys.stderr)

    auth = get_creds()
    if auth is None:
        soft_exit('BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set — skipping.')
    repo = get_repo_info()
    if repo is None:
        soft_exit('Not a Bitbucket remote — skipping.')

    cutoff = None
    if args.since_hours:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=args.since_hours))

    api_base = repo_api_base(repo)
    prs: list[dict] = []
    url = (f'{api_base}/pullrequests?state=MERGED&state=OPEN&state=DECLINED'
           f'&sort=-updated_on&pagelen=50'
           f'&fields=values.id,values.title,values.state,values.updated_on,next')
    while url and len(prs) < args.prs:
        page = bb_get(url, auth)
        if page is None:
            break
        stop = False
        for pr in page.get('values', []):
            if cutoff is not None:
                try:
                    updated = datetime.datetime.fromisoformat(
                        (pr.get('updated_on') or '').replace('Z', '+00:00'))
                except ValueError:
                    updated = None
                # Sorted by -updated_on: first PR older than the window ends the walk.
                if updated is not None and updated < cutoff:
                    stop = True
                    break
            prs.append(pr)
        if stop:
            break
        url = page.get('next')
    prs = prs[:args.prs]
    if not prs:
        if args.since_hours:
            print(f'  ↷ No PR activity in the last {args.since_hours}h — nothing to digest.',
                  file=sys.stderr)
            out_path.write_text(json.dumps({'findings': [], 'dimensions': {}}, indent=2))
            sys.exit(3 if args.digest else 0)
        soft_exit('No PRs found (or API unreachable).')

    findings: list[dict] = []
    for pr in prs:
        comments = fetch_all_comments(api_base, pr['id'], auth)
        for c in comments:
            body = (c.get('content', {}) or {}).get('raw', '') or ''
            cls = classify_finding(body)
            if cls is None:
                continue
            state, meta = cls
            inline = c.get('inline', {}) or {}
            findings.append({
                'pr': pr['id'],
                'pr_state': pr.get('state', ''),
                'comment_id': c.get('id'),
                'path': inline.get('path', '') or meta.get('path', ''),
                'dim': meta.get('dim', ''),
                'severity': meta.get('severity', ''),
                'state': state,
                'reason': meta.get('reason', ''),
            })

    dims = aggregate(findings)
    out_path.write_text(json.dumps({
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'prs_scanned': [p['id'] for p in prs],
        'findings': findings,
        'dimensions': dims,
    }, indent=2))

    total = len(findings)
    print(f'  ✓ {total} finding(s) across {len(prs)} PR(s) → {out_path}', file=sys.stderr)
    if total:
        print('\n  Dim   posted  resolved  dismissed  open', file=sys.stderr)
        for dim in sorted(dims):
            r = dims[dim]
            print(f'  §{dim:<5}{r["posted"]:>5}{r["resolved"]:>9}'
                  f'{r["dismissed"]:>10}{r["open"]:>6}', file=sys.stderr)
        reasons = [(d, why) for d, r in dims.items() for why in r['dismissal_reasons']]
        if reasons:
            print('\n  Dismissal reasons (false-positive candidates):', file=sys.stderr)
            for dim, why in reasons:
                print(f'  - §{dim}: {why}', file=sys.stderr)

    if args.digest:
        if not total and args.since_hours:
            print('  ↷ No findings in the window — digest not written (exit 3).',
                  file=sys.stderr)
            sys.exit(3)
        Path(args.digest).write_text(build_digest(findings, dims, prs, window))
        print(f'  ✓ Digest → {args.digest}', file=sys.stderr)


if __name__ == '__main__':
    main()
