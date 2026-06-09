#!/usr/bin/env python3
"""
update_resolved.py — mark an AI review comment as resolved on Bitbucket.

Usage:
    update_resolved.py --comment-id=<ID> --fix-sha=<SHA>

Fetches the comment, prepends a ✅ resolved banner with the commit reference,
replaces the <!-- ai-review:open --> marker with <!-- ai-review:resolved -->,
PUTs the updated body back to Bitbucket, and POSTs to the comment's
/resolve endpoint so the inline thread shows as ✓ resolved in the
Bitbucket UI (collapsed, filterable).

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import (
    bb_get, bb_post_status, bb_put, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)


def die(msg: str) -> None:
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(1)


def get_commit_subject(sha: str) -> str:
    r = subprocess.run(
        ['git', 'log', '--format=%s', '-1', sha],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ''


def build_resolved_body(original_body: str, fix_sha: str) -> str:
    short_sha      = fix_sha[:7]
    commit_subject = get_commit_subject(fix_sha)
    subject_part   = f' — {commit_subject}' if commit_subject else ''
    cleaned = re.sub(r'\s*<!--\s*ai-review:open:[a-f0-9]+\s*-->', '',
                     original_body).rstrip()
    return (
        f'✅ **Addressed in `{short_sha}`**{subject_part}\n\n'
        f'<!-- ai-review:resolved:{fix_sha} -->\n\n'
        f'---\n\n'
        f'*(Original review)*\n\n'
        f'{cleaned}'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Mark an AI review comment as resolved.')
    parser.add_argument('--comment-id', required=True, type=int)
    parser.add_argument('--fix-sha',    required=True)
    args = parser.parse_args()

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

    comment_url   = f'{api_base}/pullrequests/{pr_id}/comments/{args.comment_id}'
    comment       = bb_get(comment_url, auth)
    if comment is None:
        die(f'could not fetch comment #{args.comment_id}.')

    original_body = comment.get('content', {}).get('raw', '')
    updated_body  = build_resolved_body(original_body, args.fix_sha)

    if not bb_put(comment_url, auth, {'content': {'raw': updated_body}}):
        die(f'PUT failed for comment #{args.comment_id}.')

    print(f'  ✅ comment #{args.comment_id} marked resolved (fix: {args.fix_sha[:7]})')

    # Also resolve the inline thread natively so it collapses in the Bitbucket
    # UI. Best-effort with a real signal on actual failures so an API change,
    # missing token scope, or 5xx doesn't silently degrade the feature.
    status, _ = bb_post_status(f'{comment_url}/resolve', auth, {})
    if status in (200, 201):
        print(f'  ✓ comment #{args.comment_id} thread resolved in Bitbucket UI')
    elif status in (404, 409):
        # 404 = thread isn't resolvable (top-level / unknown), 409 = already resolved.
        print(
            f'  ↷ comment #{args.comment_id} thread resolution skipped '
            '(already resolved or not an inline thread)'
        )
    else:
        detail = f'HTTP {status}' if status else 'transport failure'
        print(
            f'  ⚠️  resolve POST for comment #{args.comment_id} returned '
            f'{detail} — body update succeeded; check token scope or API path.',
            file=sys.stderr,
        )


if __name__ == '__main__':
    main()
