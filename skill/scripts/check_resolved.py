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
import subprocess
import sys
import urllib.parse
from pathlib import Path


def die(msg: str) -> None:
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(1)


def load_target() -> dict | None:
    """Read .ai-review/target.json when setup_target.sh created a worktree."""
    p = Path('.ai-review/target.json')
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_creds() -> tuple[str, str]:
    email = os.environ.get('BITBUCKET_EMAIL', '')
    token = os.environ.get('BITBUCKET_API_TOKEN', '')
    if not email or not token:
        die('BITBUCKET_EMAIL and BITBUCKET_API_TOKEN must be set.')
    return email, token


def get_repo_info() -> tuple[str, str]:
    r = subprocess.run(['git', 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die('no git remote "origin" found.')
    m = re.search(r'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$', r.stdout.strip())
    if not m:
        die(f'not a Bitbucket remote: {r.stdout.strip()}')
    return m.group(1), m.group(2)


def get_branch() -> str:
    r = subprocess.run(['git', 'branch', '--show-current'],
                       capture_output=True, text=True)
    return r.stdout.strip()


def curl_get(url: str, auth: tuple[str, str]) -> dict:
    r = subprocess.run(
        ['curl', '-sSf', '-u', f'{auth[0]}:{auth[1]}', url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        die(f'Bitbucket API request failed: {r.stderr.strip() or r.stdout.strip()}')
    return json.loads(r.stdout)


def find_pr_id(api_base: str, auth: tuple[str, str], branch: str) -> str:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    data = curl_get(f'{api_base}/pullrequests?q={q}&fields=values.id', auth)
    prs = data.get('values', [])
    if not prs:
        die(f'no open PR for branch "{branch}".')
    return str(prs[0]['id'])


def fetch_all_comments(api_base: str, pr_id: str, auth: tuple[str, str]) -> list[dict]:
    """Fetch all comments on the PR, following pagination."""
    comments = []
    url: str | None = f'{api_base}/pullrequests/{pr_id}/comments?pagelen=50'
    while url:
        page = curl_get(url, auth)
        comments.extend(page.get('values', []))
        url = page.get('next')
    return comments


def extract_open_sha(body: str) -> str | None:
    """Return the SHA from <!-- ai-review:open:{sha} --> or None."""
    m = re.search(r'<!--\s*ai-review:open:([a-f0-9]+)\s*-->', body)
    return m.group(1) if m else None


def is_already_resolved(body: str) -> bool:
    return bool(re.search(r'<!--\s*ai-review:resolved:', body))


def extract_problem(body: str) -> str:
    """Extract the plain-English problem statement from section 1 of the comment."""
    m = re.search(
        r'#{1,4}\s*1\.\s+The problem[^\n]*\n(.*?)(?=\n#{1,4}\s*2\.|\Z)',
        body, re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return ''


def main() -> None:
    target   = load_target()
    auth     = get_creds()
    workspace, repo_slug = get_repo_info()
    branch   = target['branch'] if target else get_branch()
    api_base = f'https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}'
    pr_id    = str(target['pr_id']) if target and target.get('pr_id') else find_pr_id(api_base, auth, branch)

    all_comments = fetch_all_comments(api_base, pr_id, auth)

    open_comments = []
    for c in all_comments:
        body = c.get('content', {}).get('raw', '')
        sha  = extract_open_sha(body)
        if sha is None:
            continue  # not an AI review comment
        if is_already_resolved(body):
            continue  # already handled

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
