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
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import (
    fetch_all_comments, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)


def soft_exit(empty: bool = True) -> None:
    if empty:
        Path('.ai-review').mkdir(exist_ok=True)
        Path('.ai-review/dismissals.json').write_text(json.dumps({
            'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'pr_id':        None,
            'dismissals':   [],
        }, indent=2))
    sys.exit(0)


def parse_dismissal(body: str) -> dict | None:
    m = re.search(r'<!--\s*ai-review:dismissed\s+(\{[^}]+\})\s*-->', body)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def main() -> None:
    target = load_target()
    print('🔍 Refreshing dismissal memory from PR...')

    auth   = get_creds()
    if auth is None:
        print('  ↷ Bitbucket creds not set — skipping dismissal refresh.')
        soft_exit()
    repo = get_repo_info()
    if repo is None:
        print('  ↷ Not a Bitbucket remote — skipping dismissal refresh.')
        soft_exit()

    branch = get_branch(target)
    if not branch or branch in ('main', 'master', 'develop'):
        print('  ↷ On a protected branch — skipping dismissal refresh.')
        soft_exit()

    api_base = repo_api_base(repo)
    pr_id    = find_pr_id(api_base, auth, branch, target)
    if pr_id is None:
        print('  ↷ No open PR for this branch — skipping dismissal refresh.')
        soft_exit()

    comments   = fetch_all_comments(api_base, pr_id, auth)
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
    n = len(dismissals)
    if n:
        print(f'  ✓ Loaded {n} dismissal(s) → .ai-review/dismissals.json')
    else:
        print('  ↷ No dismissals on this PR — .ai-review/dismissals.json written (empty).')


if __name__ == '__main__':
    main()
