#!/usr/bin/env python3
"""
update_resolved.py — mark an AI review comment as resolved on Bitbucket.

Usage:
    update_resolved.py --comment-id=<ID> --fix-sha=<SHA>

Fetches the comment, prepends a ✅ resolved banner with the commit reference,
replaces the <!-- ai-review:open --> marker with <!-- ai-review:resolved -->,
and PUTs the updated body back to Bitbucket.

Required env vars:
  BITBUCKET_EMAIL       Bitbucket account email
  BITBUCKET_API_TOKEN   API token with Pull requests: write scope
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse


def die(msg: str) -> None:
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(1)


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
        die(f'GET failed: {r.stderr.strip() or r.stdout.strip()}')
    return json.loads(r.stdout)


def curl_put(url: str, auth: tuple[str, str], body: str) -> None:
    r = subprocess.run(
        ['curl', '-sSf', '-u', f'{auth[0]}:{auth[1]}',
         '-X', 'PUT',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({'content': {'raw': body}}),
         url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        die(f'PUT failed: {r.stderr.strip() or r.stdout.strip()}')


def find_pr_id(api_base: str, auth: tuple[str, str], branch: str) -> str:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    data = curl_get(f'{api_base}/pullrequests?q={q}&fields=values.id', auth)
    prs = data.get('values', [])
    if not prs:
        die(f'no open PR for branch "{branch}".')
    return str(prs[0]['id'])


def get_commit_subject(sha: str) -> str:
    """Return the first line of the commit message for sha."""
    r = subprocess.run(
        ['git', 'log', '--format=%s', '-1', sha],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ''


def build_resolved_body(original_body: str, fix_sha: str) -> str:
    short_sha     = fix_sha[:7]
    commit_subject = get_commit_subject(fix_sha)
    subject_part   = f' — {commit_subject}' if commit_subject else ''

    # Remove the open marker from the original body
    cleaned = re.sub(r'\s*<!--\s*ai-review:open:[a-f0-9]+\s*-->', '', original_body).rstrip()

    banner = (
        f'✅ **Addressed in `{short_sha}`**{subject_part}\n\n'
        f'<!-- ai-review:resolved:{fix_sha} -->\n\n'
        f'---\n\n'
        f'*(Original review)*\n\n'
        f'{cleaned}'
    )
    return banner


def main() -> None:
    parser = argparse.ArgumentParser(description='Mark an AI review comment as resolved.')
    parser.add_argument('--comment-id', required=True, type=int)
    parser.add_argument('--fix-sha',    required=True)
    args = parser.parse_args()

    auth = get_creds()
    workspace, repo_slug = get_repo_info()
    branch   = get_branch()
    api_base = f'https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}'
    pr_id    = find_pr_id(api_base, auth, branch)

    comment_url  = f'{api_base}/pullrequests/{pr_id}/comments/{args.comment_id}'
    comment      = curl_get(comment_url, auth)
    original_body = comment.get('content', {}).get('raw', '')

    updated_body = build_resolved_body(original_body, args.fix_sha)
    curl_put(comment_url, auth, updated_body)

    short_sha = args.fix_sha[:7]
    print(f'  ✅ comment #{args.comment_id} marked resolved (fix: {short_sha})')


if __name__ == '__main__':
    main()
