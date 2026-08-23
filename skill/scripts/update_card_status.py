#!/usr/bin/env python3
"""
update_card_status.py — transition the linked Jira card after a review run.

Usage:
    update_card_status.py --has-open-findings={true|false} [--ticket=KEY]

Decision rule:
- has-open-findings=true  → transition to JIRA_FAILED_STATUS (default "Failed Code Review")
- has-open-findings=false → transition to JIRA_PASSED_STATUS (default "Ready To Test")

Only cards currently sitting in a review column are moved: if the card's current
status is not in JIRA_SOURCE_STATUSES (default "Code Review,Failed Code Review"),
the sync skips. This stops the pipeline yanking cards that are still In Progress,
already in QA, or Done. "Failed Code Review" is an eligible source so a card that
failed a previous run can advance to "Ready To Test" once a re-run comes back
clean.

The script auto-detects the ticket key from the current branch (regex `[A-Z]+-\\d+`)
unless `--ticket` is passed. It is **idempotent** — if the card is already in
the target status, it no-ops. It **soft-exits on every failure path** so a Jira
hiccup never fails the review run itself.

Required env vars:
  JIRA_BASE_URL        e.g. https://yourcompany.atlassian.net (no trailing /rest)
  JIRA_EMAIL           Atlassian account email (falls back to BITBUCKET_EMAIL)
  JIRA_API_TOKEN       Atlassian API token   (falls back to BITBUCKET_API_TOKEN)

Optional env vars:
  JIRA_FAILED_STATUS    defaults to "Failed Code Review"
  JIRA_PASSED_STATUS    defaults to "Ready To Test"
  JIRA_SOURCE_STATUSES  comma-separated statuses eligible to be moved;
                        defaults to "Code Review,Failed Code Review"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Atlassian project keys: start with a letter, may contain letters/digits/underscores,
# then "-" then the issue number. `\b` boundaries stop accidental matches inside
# lowercase identifiers like "feat-123-foo".
TICKET_PATTERN = re.compile(r'\b([A-Z][A-Z0-9_]*-\d+)\b')


def soft_exit(msg: str = '') -> None:
    if msg:
        print(f'  ↷ {msg}', file=sys.stderr)
    sys.exit(0)


def extract_ticket_id(text: str) -> str | None:
    """Return the first JIRA-style key in `text`, or None."""
    if not text:
        return None
    m = TICKET_PATTERN.search(text)
    return m.group(1) if m else None


def parse_statuses(raw: str) -> list[str]:
    """Split a comma-separated status list, trimming blanks."""
    return [s.strip() for s in (raw or '').split(',') if s.strip()]


def is_eligible_source(current: str, sources: list[str]) -> bool:
    """True when `current` matches one of `sources` (case-insensitive)."""
    cf = (current or '').casefold()
    return any(cf == s.casefold() for s in sources)


def detect_ticket_from_branch() -> str | None:
    r = subprocess.run(['git', 'branch', '--show-current'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return extract_ticket_id(r.stdout.strip())


def branch_candidates() -> list[str]:
    """Branch names to scan for a ticket key, most reliable first.

    1. `.ai-review/target.json` — target mode (--pr/--branch, which is what CI
       runs) checks out a DETACHED worktree, so `git branch --show-current`
       prints nothing there; the target file carries the real branch.
    2. `BITBUCKET_BRANCH` — provided by Bitbucket Pipelines even when git
       state is unhelpful.
    3. The current git branch — normal local runs.
    """
    names: list[str] = []
    try:
        with open('.ai-review/target.json') as f:
            names.append((json.load(f).get('branch') or ''))
    except (OSError, json.JSONDecodeError):
        pass
    names.append(os.environ.get('BITBUCKET_BRANCH', ''))
    return names


def detect_ticket() -> str | None:
    for name in branch_candidates():
        ticket = extract_ticket_id(name)
        if ticket:
            return ticket
    return detect_ticket_from_branch()


def jira_curl(method: str, url: str, auth: str,
              body: dict | None = None) -> tuple[int, dict | None]:
    """Return (http_status, parsed_body_or_None). status==0 means transport failure."""
    cmd = ['curl', '-sS', '-w', '\n__HTTP__%{http_code}',
           '-u', auth,
           '-X', method,
           '-H', 'Content-Type: application/json',
           '-H', 'Accept: application/json']
    if body is not None:
        cmd.extend(['-d', json.dumps(body)])
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--has-open-findings', required=True,
                        choices=['true', 'false'])
    parser.add_argument('--ticket', default=None,
                        help='Override branch-based ticket detection.')
    args = parser.parse_args()

    print('🔍 Syncing Jira card status...', file=sys.stderr)

    base_url = os.environ.get('JIRA_BASE_URL', '').rstrip('/')
    email    = os.environ.get('JIRA_EMAIL') or os.environ.get('BITBUCKET_EMAIL', '')
    token    = os.environ.get('JIRA_API_TOKEN') or os.environ.get('BITBUCKET_API_TOKEN', '')

    if not base_url:
        soft_exit('JIRA_BASE_URL not set — skipping Jira sync.')
    if not (email and token):
        soft_exit('JIRA_EMAIL / JIRA_API_TOKEN not set — skipping Jira sync.')

    ticket = args.ticket or detect_ticket()
    if not ticket:
        soft_exit('No JIRA-style ticket detected (target.json / BITBUCKET_BRANCH / git branch) — skipping Jira sync.')

    failed_status = os.environ.get('JIRA_FAILED_STATUS', 'Failed Code Review')
    passed_status = os.environ.get('JIRA_PASSED_STATUS', 'Ready To Test')
    sources = parse_statuses(os.environ.get(
        'JIRA_SOURCE_STATUSES', 'Code Review,Failed Code Review'))
    target = failed_status if args.has_open_findings == 'true' else passed_status

    auth = f'{email}:{token}'

    # 1) Fetch current status.
    status, issue = jira_curl(
        'GET',
        f'{base_url}/rest/api/3/issue/{ticket}?fields=status',
        auth,
    )
    if status != 200 or not issue:
        hint = ''
        if status in (401, 403, 404):
            # Jira answers 404 (hiding the issue) when the token authenticates
            # but has no Jira access — e.g. the BITBUCKET_API_TOKEN fallback
            # with a Pull-requests-only scope.
            hint = (' If this card exists, the token has no Jira access — set '
                    'JIRA_API_TOKEN to a token with read:jira-work + write:jira-work.')
        soft_exit(f'Could not fetch Jira issue {ticket} (HTTP {status}) — skipping.{hint}')

    current = ((issue.get('fields') or {}).get('status') or {}).get('name', '') or '?'
    print(f'  Ticket {ticket}: currently "{current}", target "{target}".', file=sys.stderr)

    if current.casefold() == target.casefold():
        print(f'  ✓ Already in "{target}" — no transition needed.', file=sys.stderr)
        return

    # Only move cards sitting in a review column — never yank a card that is
    # still being worked on, already in QA, or done.
    if not is_eligible_source(current, sources):
        soft_exit(
            f'"{current}" is not an eligible source status '
            f'({", ".join(sources)}) — leaving the card where it is.'
        )

    # 2) List available transitions.
    status, t_data = jira_curl(
        'GET',
        f'{base_url}/rest/api/3/issue/{ticket}/transitions',
        auth,
    )
    if status != 200 or not t_data:
        soft_exit(f'Could not list transitions for {ticket} (HTTP {status}) — skipping.')

    transitions = t_data.get('transitions', []) or []
    matching = next(
        (t for t in transitions
         if (t.get('to') or {}).get('name', '').casefold() == target.casefold()),
        None,
    )
    if not matching:
        available = ', '.join(
            (t.get('to') or {}).get('name', '?') for t in transitions
        ) or 'none'
        soft_exit(
            f'No transition from "{current}" → "{target}" available '
            f'(workflow exposes: {available}) — skipping.'
        )

    # 3) Apply the transition.
    if os.environ.get('AI_REVIEW_DRY_RUN'):
        soft_exit(f'DRY RUN — would transition {ticket} "{current}" → "{target}".')

    status, _ = jira_curl(
        'POST',
        f'{base_url}/rest/api/3/issue/{ticket}/transitions',
        auth,
        body={'transition': {'id': matching['id']}},
    )
    if status not in (200, 204):
        print(
            f'  ⚠️  Transition POST for {ticket} returned HTTP {status} — '
            'card may not have moved; check token scope or workflow permissions.',
            file=sys.stderr,
        )
        return

    print(f'  ✓ Transitioned {ticket} → "{target}".', file=sys.stderr)


if __name__ == '__main__':
    main()
