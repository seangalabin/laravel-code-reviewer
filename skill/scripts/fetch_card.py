#!/usr/bin/env python3
"""
fetch_card.py — fetch the linked Jira card over REST, for Step 4 (card context).

Why this exists: Step 4 prefers the Atlassian MCP tools, but CI cannot reach them.
`ai-review-ci` runs `claude --permission-mode dontAsk` with an explicit tool
allowlist (Read/Write/Edit/Glob/Grep/Bash/TodoWrite), and dontAsk auto-denies
everything outside it — including every `mcp__claude_ai_Atlassian__*` tool. So in
CI the card fetch, the 4a file-relatedness check, the 4b discussion-decision
check, and the "MANDATORY" 4c implementation-context hunt all silently degraded
to the PR-body fallback. This script closes that gap with plain curl, which Bash
already permits, so CI gets the same card context an interactive run gets.

Credentials and ticket detection follow update_card_status.py exactly — same env
vars, same fallbacks, same soft-fail contract. Anything missing prints a reason
to stderr and exits 0; the review must never fail because Jira was unreachable.

  JIRA_BASE_URL    required (e.g. https://acme.atlassian.net)
  JIRA_EMAIL       falls back to BITBUCKET_EMAIL
  JIRA_API_TOKEN   falls back to BITBUCKET_API_TOKEN

stdout discipline: a single JSON object, or nothing at all. Every diagnostic goes
to stderr, so this is safe to batch alongside the other fetch scripts.

Usage:
    fetch_card.py                       # auto-detect the ticket key
    fetch_card.py --ticket=B20-11233    # explicit
    fetch_card.py --no-comments         # skip the comment fetch (1 call instead of 2)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update_card_status import (  # noqa: E402  — shared helpers, single source of truth
    detect_ticket,
    extract_ticket_id,
    jira_curl,
    soft_exit,
)

# Jira Cloud returns rich text as ADF (Atlassian Document Format) — a nested node
# tree, not a string. Only these node types carry text or structure worth keeping;
# everything else (media, panels, extensions) is flattened through its children.
ADF_BLOCK_NODES = {
    'paragraph', 'heading', 'blockquote', 'listItem', 'codeBlock',
    'tableRow', 'tableCell', 'tableHeader', 'panel', 'taskItem',
}
COMMENT_LIMIT = 30
BODY_CHAR_LIMIT = 6000


def adf_to_text(node: object, depth: int = 0) -> str:
    """Flatten an ADF document to plain text.

    Returns '' for anything unrecognised rather than raising — a card whose
    description uses a node type we don't model must still yield its other text.
    """
    if node is None:
        return ''
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return ''.join(adf_to_text(n, depth) for n in node)
    if not isinstance(node, dict):
        return ''

    ntype = node.get('type', '')
    if ntype == 'text':
        return node.get('text', '')
    if ntype == 'hardBreak':
        return '\n'
    if ntype == 'mention':
        return '@' + (node.get('attrs', {}) or {}).get('text', '').lstrip('@')
    if ntype == 'inlineCard':
        return (node.get('attrs', {}) or {}).get('url', '')
    if ntype == 'rule':
        return '\n---\n'

    inner = adf_to_text(node.get('content'), depth + 1)
    if ntype == 'bulletList' or ntype == 'orderedList':
        return inner
    if ntype == 'listItem' or ntype == 'taskItem':
        return f'- {inner.strip()}\n'
    if ntype in ('tableCell', 'tableHeader'):
        return f'{inner.strip()} | '
    if ntype == 'tableRow':
        return f'{inner.rstrip(" |")}\n'
    if ntype in ADF_BLOCK_NODES:
        return f'{inner}\n'
    return inner


def plain_text(field: object) -> str:
    """Normalise a Jira text field — ADF dict, plain string, or absent."""
    if isinstance(field, dict):
        return adf_to_text(field).strip()
    if isinstance(field, str):
        return field.strip()
    return ''


def clamp(text: str, limit: int = BODY_CHAR_LIMIT) -> str:
    """Cap a field so one enormous card can't dominate the review's context."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f'\n… [truncated, {len(text) - limit} more chars]'


def main() -> None:
    parser = argparse.ArgumentParser(description='Fetch Jira card context as JSON.')
    parser.add_argument('--ticket', default='',
                        help='Ticket key (e.g. B20-11233). Auto-detected when omitted.')
    parser.add_argument('--no-comments', action='store_true',
                        help='Skip the comments call.')
    args = parser.parse_args()

    print('🔍 Fetching Jira card context...', file=sys.stderr)

    base_url = os.environ.get('JIRA_BASE_URL', '').rstrip('/')
    email    = os.environ.get('JIRA_EMAIL') or os.environ.get('BITBUCKET_EMAIL', '')
    token    = os.environ.get('JIRA_API_TOKEN') or os.environ.get('BITBUCKET_API_TOKEN', '')

    if not base_url:
        soft_exit('JIRA_BASE_URL not set — no card context (the review continues without it).')
    if not (email and token):
        soft_exit('Jira credentials not set — no card context (the review continues without it).')

    ticket = extract_ticket_id(args.ticket) if args.ticket else detect_ticket()
    if not ticket:
        soft_exit('No Jira key found in target.json / BITBUCKET_BRANCH / git branch — no card context.')

    auth = f'{email}:{token}'
    status, issue = jira_curl(
        'GET',
        f'{base_url}/rest/api/3/issue/{ticket}'
        '?fields=summary,description,status,issuetype,labels,priority',
        auth,
    )
    if status == 0:
        soft_exit(f'Could not reach Jira (transport failure) — no card context for {ticket}.')
    if status == 404:
        soft_exit(f'{ticket} not found in Jira — no card context.')
    if status in (401, 403):
        soft_exit(f'Jira rejected the credentials ({status}) — no card context for {ticket}.')
    if status >= 400 or not isinstance(issue, dict):
        soft_exit(f'Jira returned {status} for {ticket} — no card context.')

    fields = issue.get('fields') or {}
    card = {
        'ticket':      ticket,
        'url':         f'{base_url}/browse/{ticket}',
        'title':       plain_text(fields.get('summary')),
        'description': clamp(plain_text(fields.get('description'))),
        'status':      ((fields.get('status') or {}).get('name') or ''),
        'type':        ((fields.get('issuetype') or {}).get('name') or ''),
        'priority':    ((fields.get('priority') or {}).get('name') or ''),
        'labels':      fields.get('labels') or [],
        'comments':    [],
    }

    # Comments are a separate call. They carry the design decisions Step 4b looks
    # for — those are raised in the thread after the description is written, so a
    # description-only fetch misses exactly the signal that check needs.
    if not args.no_comments:
        c_status, payload = jira_curl(
            'GET',
            f'{base_url}/rest/api/3/issue/{ticket}/comment'
            f'?maxResults={COMMENT_LIMIT}&orderBy=created',
            auth,
        )
        if c_status == 0 or c_status >= 400 or not isinstance(payload, dict):
            print(f'  ↷ Could not fetch {ticket} comments ({c_status}) — '
                  'description-only context.', file=sys.stderr)
        else:
            for c in (payload.get('comments') or []):
                card['comments'].append({
                    'author':  ((c.get('author') or {}).get('displayName') or 'unknown'),
                    'created': c.get('created', ''),
                    'body':    clamp(plain_text(c.get('body')), 2000),
                })

    print(f'  ✓ Loaded {ticket} — "{card["title"][:60]}" '
          f'({len(card["comments"])} comment(s), status: {card["status"]}).',
          file=sys.stderr)
    print(json.dumps(card, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
