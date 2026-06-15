#!/usr/bin/env python3
"""
post_reply.py — post a threaded reply to a Bitbucket PR comment.

Reads the reply body from stdin and posts it as a reply to --parent-id. The
reply inherits the parent thread's inline anchor, so no path/line is needed.
Appends the hidden <!-- ai-review:reply --> marker so future check_replies.py
runs recognise the bot's own answer and don't reply to it again.

Usage:
    post_reply.py --parent-id=<COMMENT_ID> <<'REPLY'
    You're right — auth is enforced by the middleware here, so this isn't an
    IDOR. Dismissing. Thanks for the context.
    REPLY

Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import (
    bb_post, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)

REPLY_MARKER = '<!-- ai-review:reply -->'


def die(msg: str) -> None:
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(1)


def ensure_reply_marker(body: str) -> str:
    """Append the anti-loop reply marker unless it's already present.

    The marker lets check_replies.py recognise a bot reply (so the bot never
    answers its own reply). Idempotent — appending twice is a no-op.
    """
    if REPLY_MARKER in body:
        return body
    return f'{body}\n\n{REPLY_MARKER}'


def main() -> None:
    parser = argparse.ArgumentParser(description='Post a threaded reply to a PR comment.')
    parser.add_argument('--parent-id', required=True, type=int)
    args = parser.parse_args()

    body = sys.stdin.read().strip()
    if not body:
        die('reply body is empty (pass it on stdin).')
    body = ensure_reply_marker(body)

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

    url  = f'{api_base}/pullrequests/{pr_id}/comments'
    resp = bb_post(url, auth, {
        'content': {'raw': body},
        'parent':  {'id': args.parent_id},
    })
    if resp is None:
        die(f'failed to post reply to comment #{args.parent_id}.')

    print(f'  ✓ replied to comment #{args.parent_id} (new comment #{resp.get("id", "?")})')


if __name__ == '__main__':
    main()
