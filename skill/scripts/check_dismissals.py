#!/usr/bin/env python3
"""
check_dismissals.py — refresh .ai-review/dismissals.json from current PR.

Reads every PR comment that was dismissed via `ai-review dismiss` and writes
the dismissal metadata to a local file. The skill checks this file before
posting findings and skips any candidate that matches an existing dismissal.

Match rule (applied by the skill, not this script):
  - same `path`
  - same `dim`
  - candidate line within ±5 of the dismissal `line`

If those all match, the finding is skipped unless --ignore-dismissals was passed.

Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
Exits silently (writing an empty dismissals.json) if creds are missing,
the remote is not Bitbucket, or no PR is open for the current branch.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path


def soft_exit(empty: bool = True) -> None:
    if empty:
        Path('.ai-review').mkdir(exist_ok=True)
        Path('.ai-review/dismissals.json').write_text(json.dumps({
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'pr_id':        None,
            'dismissals':   [],
        }, indent=2))
    sys.exit(0)


def get_creds() -> tuple[str, str] | None:
    email = os.environ.get('BITBUCKET_EMAIL', '')
    token = os.environ.get('BITBUCKET_API_TOKEN', '')
    return (email, token) if email and token else None


def get_repo_info() -> tuple[str, str] | None:
    r = subprocess.run(['git', 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$', r.stdout.strip())
    return (m.group(1), m.group(2)) if m else None


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
    out: list[dict] = []
    url: str | None = f'{api_base}/pullrequests/{pr_id}/comments?pagelen=50'
    while url:
        page = curl(url, auth)
        if page is None:
            break
        out.extend(page.get('values', []))
        url = page.get('next')
    return out


def parse_dismissal(body: str) -> dict | None:
    m = re.search(r'<!--\s*ai-review:dismissed\s+(\{[^}]+\})\s*-->', body)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def main() -> None:
    auth = get_creds()
    if auth is None:
        soft_exit()
    repo = get_repo_info()
    if repo is None:
        soft_exit()
    branch = get_branch()
    if branch in ('main', 'master', 'develop'):
        soft_exit()

    api_base = f'https://api.bitbucket.org/2.0/repositories/{repo[0]}/{repo[1]}'
    pr_id = find_pr_id(api_base, auth, branch)
    if pr_id is None:
        soft_exit()

    comments = fetch_all_comments(api_base, pr_id, auth)

    dismissals = []
    for c in comments:
        body = c.get('content', {}).get('raw', '')
        meta = parse_dismissal(body)
        if not meta:
            continue
        dismissals.append({
            'comment_id':   c['id'],
            'path':         meta.get('path', ''),
            'line':         meta.get('line'),
            'sig':          meta.get('sig', ''),
            'dim':          meta.get('dim', ''),
            'severity':     meta.get('severity', ''),
            'reason':       meta.get('reason', ''),
            'dismissed_at': c.get('updated_on') or c.get('created_on'),
        })

    Path('.ai-review').mkdir(exist_ok=True)
    out = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'pr_id':        int(pr_id),
        'dismissals':   dismissals,
    }
    Path('.ai-review/dismissals.json').write_text(json.dumps(out, indent=2))
    print(f'  Loaded {len(dismissals)} dismissal(s) → .ai-review/dismissals.json')


if __name__ == '__main__':
    main()
