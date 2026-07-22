#!/usr/bin/env python3
"""
check_resolved.py — fetch open AI review comments from the current PR.

Outputs a JSON array to stdout. Each element:
  {
    "id":         123,
    "path":       "app/Services/OrderService.php",
    "line":       47,
    "posted_sha": "abc1234...",
    "problem":    "Plain-English problem extracted from section 1 of the comment.",
    "body":       "...full original comment body..."
  }

Exits 0 with an empty array [] if no open AI comments exist.

Side effect: writes `.ai-review/posted.json` — the index of every AI *finding*
comment already on the PR (open OR resolved, excluding dismissed ones, which
`check_dismissals.py` owns). The reviewer's Step 8 dedup filter reads this to
skip re-posting a finding that is already on the PR: still-open findings would
be duplicates, resolved findings would be resurrected. Each entry:
  { "comment_id": 123, "path": "...", "line": 47, "dim": "3a",
    "severity": "🔴", "resolved": false }

Required env vars:
  BITBUCKET_EMAIL       Bitbucket account email
  BITBUCKET_API_TOKEN   API token with Pull requests: write scope
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
    bb_get, fetch_all_comments, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)


def die(msg: str) -> None:
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(1)


def extract_open_sha(body: str) -> str | None:
    m = re.search(r'<!--\s*ai-review:open:([a-f0-9]+)\s*-->', body)
    return m.group(1) if m else None


def is_already_resolved(body: str) -> bool:
    return bool(re.search(r'<!--\s*ai-review:resolved:', body))


def is_dismissed(body: str) -> bool:
    return bool(re.search(r'<!--\s*ai-review:dismissed', body))


def is_finding(body: str) -> bool:
    """A top-level AI finding comment — carries an open or resolved marker.
    Reply comments (ai-review:reply / ai-fixer:reply) do not match."""
    return bool(re.search(r'<!--\s*ai-review:(open|resolved):', body))


def extract_meta(body: str) -> dict:
    """Extract the dim/severity meta marker, if present. Survives into resolved
    bodies — update_resolved.py strips only the open marker, not the meta one."""
    m = re.search(r'<!--\s*ai-review:meta\s+(\{[^}]+\})\s*-->', body)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def build_posted_index(all_comments: list) -> list:
    """Every AI finding already on the PR, open or resolved (dismissed excluded
    — check_dismissals.py owns those). Used by the reviewer's dedup filter to
    avoid re-posting a finding that is already present."""
    posted = []
    for c in all_comments:
        body = c.get('content', {}).get('raw', '')
        if is_dismissed(body) or not is_finding(body):
            continue
        inline = c.get('inline', {}) or {}
        meta   = extract_meta(body)
        posted.append({
            'comment_id': c.get('id'),
            'path':       inline.get('path', ''),
            'line':       inline.get('to'),
            'dim':        meta.get('dim', ''),
            'severity':   meta.get('severity', ''),
            'resolved':   is_already_resolved(body),
        })
    return posted


def extract_problem(body: str) -> str:
    m = re.search(
        r'#{1,4}\s*1\.\s+The problem[^\n]*\n(.*?)(?=\n#{1,4}\s*2\.|\Z)',
        body, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else ''


def main() -> None:
    target = load_target()
    auth   = get_creds()
    if auth is None:
        die('BITBUCKET_EMAIL and BITBUCKET_API_TOKEN must be set.')
    repo = get_repo_info()
    if repo is None:
        die('no git remote "origin" found or not a Bitbucket URL.')

    print('🔍 Checking previously posted AI comments...', file=sys.stderr)

    branch   = get_branch(target)
    api_base = repo_api_base(repo)
    pr_id    = find_pr_id(api_base, auth, branch, target)
    if pr_id is None:
        die(f'no open PR for branch "{branch}".')

    all_comments  = fetch_all_comments(api_base, pr_id, auth)
    open_comments = []
    for c in all_comments:
        body = c.get('content', {}).get('raw', '')
        sha  = extract_open_sha(body)
        if sha is None or is_already_resolved(body):
            continue
        inline = c.get('inline', {})
        open_comments.append({
            'id':         c['id'],
            'path':       inline.get('path', ''),
            'line':       inline.get('to'),
            'posted_sha': sha,
            'problem':    extract_problem(body),
            'body':       body,
        })

    # Write the posted-findings index (open + resolved) for the dedup filter.
    posted = build_posted_index(all_comments)
    Path('.ai-review').mkdir(exist_ok=True)
    Path('.ai-review/posted.json').write_text(json.dumps({
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'pr_id':        int(pr_id),
        'posted':       posted,
    }, indent=2))
    n_resolved = sum(1 for p in posted if p['resolved'])
    print(f'  ✓ Indexed {len(posted)} posted finding(s) '
          f'({n_resolved} resolved) → .ai-review/posted.json', file=sys.stderr)

    n = len(open_comments)
    if n:
        print(f'  ✓ Found {n} open AI comment(s) to evaluate for resolution.',
              file=sys.stderr)
    else:
        print('  ↷ No open AI comments on this PR — nothing to re-evaluate.',
              file=sys.stderr)

    print(json.dumps(open_comments, indent=2))


if __name__ == '__main__':
    main()
