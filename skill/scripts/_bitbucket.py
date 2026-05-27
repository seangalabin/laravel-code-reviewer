"""
Shared Bitbucket / git helpers for code-reviewer scripts.

All functions return None (or False / []) on failure rather than calling
sys.exit(). Callers choose how to handle errors (die(), soft_exit(), etc.).

Import from sibling scripts via:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _bitbucket import load_target, get_creds, ...
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path


def load_target() -> dict | None:
    """Read .ai-review/target.json when setup_target.sh created a worktree."""
    p = Path('.ai-review/target.json')
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


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


def get_branch(target: dict | None = None) -> str:
    if target is not None:
        return target.get('branch', '')
    r = subprocess.run(['git', 'branch', '--show-current'],
                       capture_output=True, text=True)
    return r.stdout.strip()


def bb_get(url: str, auth: tuple[str, str]) -> dict | None:
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


def bb_put(url: str, auth: tuple[str, str], body: dict) -> bool:
    r = subprocess.run(
        ['curl', '-sSf', '-u', f'{auth[0]}:{auth[1]}',
         '-X', 'PUT',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(body),
         url],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def find_pr_id(api_base: str, auth: tuple[str, str], branch: str,
               target: dict | None = None) -> str | None:
    if target and target.get('pr_id'):
        return str(target['pr_id'])
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    data = bb_get(f'{api_base}/pullrequests?q={q}&fields=values.id', auth)
    if not data:
        return None
    prs = data.get('values', [])
    return str(prs[0]['id']) if prs else None


def fetch_all_comments(api_base: str, pr_id: str,
                       auth: tuple[str, str]) -> list[dict]:
    out: list[dict] = []
    url: str | None = f'{api_base}/pullrequests/{pr_id}/comments?pagelen=50'
    while url:
        page = bb_get(url, auth)
        if page is None:
            break
        out.extend(page.get('values', []))
        url = page.get('next')
    return out


def repo_api_base(repo: tuple[str, str]) -> str:
    return f'https://api.bitbucket.org/2.0/repositories/{repo[0]}/{repo[1]}'
