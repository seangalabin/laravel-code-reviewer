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
import sys
import urllib.parse
from pathlib import Path

# Set once we've warned about rejected credentials, so paginated / repeated
# calls don't spam the same message.
_AUTH_WARNED = False


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
    # Capture the HTTP status (instead of letting `curl -f` collapse every
    # non-2xx into a bare failure) so a rejected token surfaces loudly rather
    # than masquerading as "no data" / "no PR".
    global _AUTH_WARNED
    r = subprocess.run(
        ['curl', '-sS', '-w', '\n__HTTP__%{http_code}', '-u', f'{auth[0]}:{auth[1]}', url],
        capture_output=True, text=True,
    )
    body, _, code = r.stdout.rpartition('__HTTP__')
    code = code.strip()
    if code in ('401', '403') and not _AUTH_WARNED:
        _AUTH_WARNED = True
        print(
            f"WARNING: Bitbucket rejected the API credentials (HTTP {code}). This is not "
            "'no PR' — your BITBUCKET_API_TOKEN is invalid, expired, or lacks Bitbucket "
            "scopes. Regenerate it at "
            "https://id.atlassian.com/manage-profile/security/api-tokens (Pull requests: "
            "read+write) and confirm BITBUCKET_EMAIL matches that Atlassian account.",
            file=sys.stderr,
        )
    if r.returncode != 0 or code not in ('200', '201'):
        return None
    try:
        return json.loads(body)
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


def bb_post_status(url: str, auth: tuple[str, str], body: dict) -> tuple[int, dict | None]:
    """POST JSON. Returns (http_status, parsed_body_or_None).

    `http_status` is 0 if curl itself failed (network/transport).
    `parsed_body_or_None` is the JSON-decoded response when present and parseable,
    otherwise None. Use this directly when you need to distinguish 2xx success
    from 4xx-soft (e.g. 404 / 409) from real failures (401, 403, 5xx, transport).
    Most callers can keep using `bb_post`.
    """
    r = subprocess.run(
        ['curl', '-sS', '-w', '\n__HTTP__%{http_code}',
         '-u', f'{auth[0]}:{auth[1]}',
         '-X', 'POST',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(body),
         url],
        capture_output=True, text=True,
    )
    out, _, code_str = r.stdout.rpartition('__HTTP__')
    if r.returncode != 0:
        return (0, None)
    try:
        status = int(code_str.strip())
    except ValueError:
        status = 0
    try:
        parsed = json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return (status, parsed)


def bb_post(url: str, auth: tuple[str, str], body: dict) -> dict | None:
    """POST JSON and return the parsed response (the created object), or None.

    Backward-compatible wrapper over `bb_post_status` — returns None for any
    non-(200|201) response. Used for creating comments / threaded replies, where
    the caller only cares about the new object on success.
    """
    status, parsed = bb_post_status(url, auth, body)
    return parsed if status in (200, 201) else None


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
