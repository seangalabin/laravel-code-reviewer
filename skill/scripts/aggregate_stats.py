#!/usr/bin/env python3
"""
aggregate_stats.py — read AI review comments on the current PR, classify
them, print a telemetry digest, and snapshot to .ai-review/stats.json.

Each AI comment carries two markers:
  <!-- ai-review:open:{sha} -->                    (always present)
  <!-- ai-review:meta {"dim":"3a","severity":"warning"} -->  (when posted with telemetry)

Resolved comments are rewritten with:
  <!-- ai-review:resolved:{fix_sha} -->

Comments older than STALE_DAYS without resolution are classified as stale.

Output:
  - Prints a human-readable digest to stdout
  - Writes .ai-review/stats.json with structured counts

Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
Exits silently if creds are missing or no PR exists.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import (
    fetch_all_comments, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)


STALE_DAYS = 14


def soft_exit(msg: str = '') -> None:
    if msg:
        print(msg, file=sys.stderr)
    sys.exit(0)


def parse_meta(body: str) -> dict:
    m = re.search(r'<!--\s*ai-review:meta\s+(\{[^}]+\})\s*-->', body)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def parse_created_at(s: str) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return datetime.datetime.now(datetime.timezone.utc)


def classify(body: str, created_on: str, now: datetime.datetime) -> str:
    if re.search(r'<!--\s*ai-review:resolved:', body):
        return 'resolved'
    if not re.search(r'<!--\s*ai-review:open:', body):
        return 'other'
    age = (now - parse_created_at(created_on)).days
    return 'stale' if age >= STALE_DAYS else 'open'


def emoji(sev: str) -> str:
    return {'critical': '🔴', 'warning': '🟡', 'suggestion': '🔵'}.get(sev, '⚪')


def print_digest(stats: dict, pr_id: str) -> None:
    total = stats['total']
    if total == 0:
        print('─── Review telemetry ───')
        print(f'PR #{pr_id}: no AI review comments yet.')
        return

    by_status = stats['by_status']
    resolved  = by_status.get('resolved', 0)
    open_     = by_status.get('open', 0)
    stale     = by_status.get('stale', 0)
    pct       = round(resolved / total * 100) if total else 0

    print('\n─── Review telemetry ───')
    print(f'PR #{pr_id}: {total} findings posted '
          f'({resolved} resolved · {pct}%, {open_} open, {stale} stale)')

    for sev in ('critical', 'warning', 'suggestion'):
        counts = stats['by_severity'].get(sev)
        if not counts:
            continue
        sev_total    = sum(counts.values())
        sev_resolved = counts.get('resolved', 0)
        tail = []
        if counts.get('open'):   tail.append(f"{counts['open']} open")
        if counts.get('stale'):  tail.append(f"{counts['stale']} stale")
        tail_str = f"  ({', '.join(tail)})" if tail else ''
        print(f'  {emoji(sev)} {sev.capitalize():11}'
              f' {sev_resolved}/{sev_total} resolved{tail_str}')

    dim_open = [
        (dim, counts.get('open', 0) + counts.get('stale', 0))
        for dim, counts in stats['by_dimension'].items()
    ]
    dim_open = sorted([(d, n) for d, n in dim_open if n > 0], key=lambda x: -x[1])
    if dim_open:
        print('\nTop open dimensions:')
        for dim, n in dim_open[:5]:
            print(f'  {dim}: {n} open')


def main() -> None:
    target = load_target()
    auth   = get_creds()
    if auth is None:
        soft_exit('  Skipping telemetry — Bitbucket credentials not set.')
    repo = get_repo_info()
    if repo is None:
        soft_exit('  Skipping telemetry — not a Bitbucket remote.')

    branch = get_branch(target)
    if not branch or branch in ('main', 'master', 'develop'):
        soft_exit()

    api_base = repo_api_base(repo)
    pr_id    = find_pr_id(api_base, auth, branch, target)
    if pr_id is None:
        soft_exit('  Skipping telemetry — no open PR for current branch.')

    now      = datetime.datetime.now(datetime.timezone.utc)
    comments = fetch_all_comments(api_base, pr_id, auth)

    by_status:    dict[str, int]             = defaultdict(int)
    by_severity:  dict[str, dict[str, int]]  = defaultdict(lambda: defaultdict(int))
    by_dimension: dict[str, dict[str, int]]  = defaultdict(lambda: defaultdict(int))
    total = 0

    for c in comments:
        body   = c.get('content', {}).get('raw', '')
        status = classify(body, c.get('created_on', ''), now)
        if status == 'other':
            continue
        total += 1
        by_status[status] += 1
        meta = parse_meta(body)
        if 'severity' in meta:
            by_severity[meta['severity']][status] += 1
        if 'dim' in meta:
            by_dimension[meta['dim']][status] += 1

    stats = {
        'generated_at': now.isoformat(),
        'pr_id':        int(pr_id),
        'total':        total,
        'by_status':    dict(by_status),
        'by_severity':  {k: dict(v) for k, v in by_severity.items()},
        'by_dimension': {k: dict(v) for k, v in by_dimension.items()},
    }

    stats_dir = Path('.ai-review')
    stats_dir.mkdir(exist_ok=True)
    (stats_dir / 'stats.json').write_text(json.dumps(stats, indent=2))

    print_digest(stats, pr_id)
    print(f'\n  Snapshot saved to .ai-review/stats.json')


if __name__ == '__main__':
    main()
