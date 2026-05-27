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

Required env vars:
  BITBUCKET_EMAIL       Bitbucket account email
  BITBUCKET_API_TOKEN   API token with Pull requests: write scope
"""

from __future__ import annotations

import json
import os
import re
import sys

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

    print(json.dumps(open_comments, indent=2))


if __name__ == '__main__':
    main()
