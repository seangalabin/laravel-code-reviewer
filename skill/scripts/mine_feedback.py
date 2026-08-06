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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prs', type=int, default=30,
                        help='How many most-recently-updated PRs to mine (default 30).')
    args = parser.parse_args()

    out_path = Path('.ai-review/feedback-report.json')
    Path('.ai-review').mkdir(exist_ok=True)

    def soft_exit(msg: str) -> None:
        print(f'  ↷ {msg}', file=sys.stderr)
        out_path.write_text(json.dumps({'findings': [], 'dimensions': {}}, indent=2))
        sys.exit(0)

    print(f'🔍 Mining reviewer feedback from the last {args.prs} PRs...', file=sys.stderr)

    auth = get_creds()
    if auth is None:
        soft_exit('BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set — skipping.')
    repo = get_repo_info()
    if repo is None:
        soft_exit('Not a Bitbucket remote — skipping.')

    api_base = repo_api_base(repo)
    prs: list[dict] = []
    url = (f'{api_base}/pullrequests?state=MERGED&state=OPEN&state=DECLINED'
           f'&sort=-updated_on&pagelen=50'
           f'&fields=values.id,values.title,values.state,next')
    while url and len(prs) < args.prs:
        page = bb_get(url, auth)
        if page is None:
            break
        prs.extend(page.get('values', []))
        url = page.get('next')
    prs = prs[:args.prs]
    if not prs:
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


if __name__ == '__main__':
    main()
