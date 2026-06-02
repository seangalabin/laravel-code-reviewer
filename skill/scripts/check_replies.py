#!/usr/bin/env python3
"""
check_replies.py — find developer replies awaiting a response on the current PR.

Outputs a JSON array to stdout. Each element is an *open* AI finding whose
comment thread ends with a developer reply the bot hasn't answered yet:

  {
    "root_id":      123,         # the AI finding comment (for dismiss/resolve)
    "reply_id":     456,         # the developer comment to reply under
    "path":         "app/Services/OrderService.php",
    "line":         47,
    "posted_sha":   "abc1234",   # SHA the finding was posted at
    "problem":      "Plain-English problem from section 1 of the finding.",
    "finding_body": "...full original finding body...",
    "reply_text":   "...the developer's latest reply...",
    "reply_author": "Jane Dev",
    "thread": [                  # ordered context, oldest -> newest
      {"id": 123, "author": "Jane Dev", "is_ai": true,  "text": "..."},
      {"id": 456, "author": "Jane Dev", "is_ai": false, "text": "..."}
    ]
  }

"Open AI finding" = a top-level comment carrying <!-- ai-review:open:SHA --> that
has not been resolved or dismissed. "Awaiting a response" = the newest
(non-deleted) comment in that thread is a human one (carries no ai-review marker).

Bot authorship is detected by the hidden ai-review markers, NOT by account: the
reviewer posts with the developer's own Bitbucket token (bring-your-own-key), so
the bot and a human reviewer can share an account. Markers are the reliable
signal, and they also stop the bot answering its own replies in a loop.

Exits 0 with an empty array [] when creds are missing, the remote is not
Bitbucket, no PR is open, or nothing is awaiting a response.

Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bitbucket import (
    fetch_all_comments, find_pr_id, get_branch, get_creds,
    get_repo_info, load_target, repo_api_base,
)

AI_MARKER_RE = re.compile(r'<!--\s*ai-review:')


def soft_exit() -> None:
    print('[]')
    sys.exit(0)


def extract_open_sha(body: str) -> str | None:
    m = re.search(r'<!--\s*ai-review:open:([a-f0-9]+)\s*-->', body)
    return m.group(1) if m else None


def is_resolved_or_dismissed(body: str) -> bool:
    return bool(re.search(r'<!--\s*ai-review:(resolved|dismissed)', body))


def is_ai_comment(body: str) -> bool:
    """A comment the bot authored — recognised by any hidden ai-review marker."""
    return bool(AI_MARKER_RE.search(body))


def extract_problem(body: str) -> str:
    m = re.search(
        r'#{1,4}\s*1\.\s+The problem[^\n]*\n(.*?)(?=\n#{1,4}\s*2\.|\Z)',
        body, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else ''


def comment_body(c: dict) -> str:
    return (c.get('content', {}) or {}).get('raw', '') or ''


def author_name(c: dict) -> str:
    return (c.get('user', {}) or {}).get('display_name', '') or 'developer'


def main() -> None:
    target = load_target()
    auth   = get_creds()
    if auth is None:
        soft_exit()
    repo = get_repo_info()
    if repo is None:
        soft_exit()

    branch = get_branch(target)
    if not branch or branch in ('main', 'master', 'develop'):
        soft_exit()

    api_base = repo_api_base(repo)
    pr_id    = find_pr_id(api_base, auth, branch, target)
    if pr_id is None:
        soft_exit()

    comments = fetch_all_comments(api_base, pr_id, auth)

    # parent_id -> [child comments]
    children: dict[int, list[dict]] = {}
    for c in comments:
        pid = (c.get('parent') or {}).get('id')
        if pid is not None:
            children.setdefault(pid, []).append(c)

    def descendants(root_id: int) -> list[dict]:
        out: list[dict] = []
        stack = list(children.get(root_id, []))
        while stack:
            c = stack.pop()
            out.append(c)
            stack.extend(children.get(c['id'], []))
        return out

    awaiting = []
    for c in comments:
        # Findings are top-level inline comments — skip anything that is a reply.
        if (c.get('parent') or {}).get('id') is not None:
            continue
        body = comment_body(c)
        sha  = extract_open_sha(body)
        if sha is None or is_resolved_or_dismissed(body):
            continue

        thread = [c] + descendants(c['id'])
        live   = [t for t in thread if not t.get('deleted')]
        if not live:
            continue

        # Newest comment in the thread by creation time (ISO8601 sorts lexically).
        newest = max(live, key=lambda t: t.get('created_on') or '')
        if is_ai_comment(comment_body(newest)):
            continue  # the bot already had the last word

        inline  = c.get('inline', {}) or {}
        ordered = sorted(live, key=lambda t: t.get('created_on') or '')
        awaiting.append({
            'root_id':      c['id'],
            'reply_id':     newest['id'],
            'path':         inline.get('path', ''),
            'line':         inline.get('to'),
            'posted_sha':   sha,
            'problem':      extract_problem(body),
            'finding_body': body,
            'reply_text':   comment_body(newest),
            'reply_author': author_name(newest),
            'thread': [{
                'id':     t['id'],
                'author': author_name(t),
                'is_ai':  is_ai_comment(comment_body(t)),
                'text':   comment_body(t),
            } for t in ordered],
        })

    print(json.dumps(awaiting, indent=2))


if __name__ == '__main__':
    main()
