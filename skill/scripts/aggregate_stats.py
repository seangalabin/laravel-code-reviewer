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
import subprocess
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path


STALE_DAYS = 14


def load_target() -> dict | None:
    """Read .ai-review/target.json when setup_target.sh created a worktree."""
    p = Path('.ai-review/target.json')
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def soft_exit(msg: str = '') -> None:
    if msg:
        print(msg, file=sys.stderr)
    sys.exit(0)


def get_creds() -> tuple[str, str] | None:
    email = os.environ.get('BITBUCKET_EMAIL', '')
    token = os.environ.get('BITBUCKET_API_TOKEN', '')
    if not email or not token:
        return None
    return email, token


def get_repo_info() -> tuple[str, str] | None:
    r = subprocess.run(['git', 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$', r.stdout.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def get_branch() -> str:
    r = subprocess.run(['git', 'branch', '--show-current'],
                       capture_output=True, text=True)
    return r.stdout.strip()


def curl(url: str, auth: tuple[str, str]) -> dict | None:
    r = subprocess.run(
        ['curl', '-sSf', '-u', f'{auth[0]}:{auth[1]}', url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def find_pr_id(api_base: str, auth: tuple[str, str], branch: str) -> str | None:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    data = curl(f'{api_base}/pullrequests?q={q}&fields=values.id', auth)
    if not data:
        return None
    prs = data.get('values', [])
    return str(prs[0]['id']) if prs else None


def fetch_all_comments(api_base: str, pr_id: str, auth: tuple[str, str]) -> list[dict]:
    comments: list[dict] = []
    url: str | None = f'{api_base}/pullrequests/{pr_id}/comments?pagelen=50'
    while url:
        page = curl(url, auth)
        if page is None:
            break
        comments.extend(page.get('values', []))
        url = page.get('next')
    return comments


def parse_meta(body: str) -> dict:
    """Extract the dim/severity meta marker, if present."""
    m = re.search(r'<!--\s*ai-review:meta\s+(\{[^}]+\})\s*-->', body)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def parse_created_at(s: str) -> datetime.datetime:
    """Bitbucket returns ISO-8601 with 'Z' or +00:00. Normalize and parse."""
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return datetime.datetime.now(datetime.timezone.utc)


def classify(body: str, created_on: str, now: datetime.datetime) -> str:
    if re.search(r'<!--\s*ai-review:resolved:', body):
        return 'resolved'
    if not re.search(r'<!--\s*ai-review:open:', body):
        return 'other'  # not an AI comment
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
    resolved = by_status.get('resolved', 0)
    open_    = by_status.get('open', 0)
    stale    = by_status.get('stale', 0)
    pct      = round(resolved / total * 100) if total else 0

    print('\n─── Review telemetry ───')
    print(f'PR #{pr_id}: {total} findings posted '
          f'({resolved} resolved · {pct}%, {open_} open, {stale} stale)')

    sev_lines = stats['by_severity']
    if sev_lines:
        print('\nBy severity:')
        for sev in ('critical', 'warning', 'suggestion'):
            counts = sev_lines.get(sev)
            if not counts:
                continue
            sev_total = sum(counts.values())
            sev_resolved = counts.get('resolved', 0)
            sev_open = counts.get('open', 0)
            sev_stale = counts.get('stale', 0)
            tail = []
            if sev_open:  tail.append(f'{sev_open} open')
            if sev_stale: tail.append(f'{sev_stale} stale')
            tail_str = f"  ({', '.join(tail)})" if tail else ''
            print(f'  {emoji(sev)} {sev.capitalize():11}'
                  f' {sev_resolved}/{sev_total} resolved{tail_str}')

    dim_open = [
        (dim, counts.get('open', 0) + counts.get('stale', 0))
        for dim, counts in stats['by_dimension'].items()
    ]
    dim_open = [(d, n) for d, n in dim_open if n > 0]
    dim_open.sort(key=lambda x: -x[1])
    if dim_open:
        print('\nTop open dimensions:')
        for dim, n in dim_open[:5]:
            print(f'  {dim}: {n} open')


def main() -> None:
    target = load_target()
    auth = get_creds()
    if auth is None:
        soft_exit('  Skipping telemetry — Bitbucket credentials not set.')
    repo = get_repo_info()
    if repo is None:
        soft_exit('  Skipping telemetry — not a Bitbucket remote.')
    branch = target['branch'] if target else get_branch()
    if not branch or branch in ('main', 'master', 'develop'):
        soft_exit()

    api_base = f'https://api.bitbucket.org/2.0/repositories/{repo[0]}/{repo[1]}'
    if target and target.get('pr_id'):
        pr_id = str(target['pr_id'])
    else:
        pr_id = find_pr_id(api_base, auth, branch)
    if pr_id is None:
        soft_exit('  Skipping telemetry — no open PR for current branch.')

    now = datetime.datetime.now(datetime.timezone.utc)
    comments = fetch_all_comments(api_base, pr_id, auth)

    by_status:    dict[str, int]                = defaultdict(int)
    by_severity:  dict[str, dict[str, int]]     = defaultdict(lambda: defaultdict(int))
    by_dimension: dict[str, dict[str, int]]     = defaultdict(lambda: defaultdict(int))
    total = 0

    for c in comments:
        body = c.get('content', {}).get('raw', '')
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
