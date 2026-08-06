"""
Unit tests for pure-logic functions in skill/scripts/ and skill/bin/.

Run:  python3 -m pytest tests/          (if pytest is available)
  or: python3 -m unittest discover tests
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Import helpers ─────────────────────────────────────────────────────────────

SCRIPTS = Path(__file__).parent.parent / 'skill' / 'scripts'
BIN     = Path(__file__).parent.parent / 'skill' / 'bin'


def load_module(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    mod_name = f'_test_{name}'
    src  = path.read_text()
    code = compile(src, str(path), 'exec')
    mod  = type(sys)(mod_name)
    mod.__file__   = str(path)
    mod.__package__ = ''
    sys.modules[mod_name] = mod   # needed for @dataclass and similar decorators
    exec(code, mod.__dict__)
    return mod


REPO_ROOT = Path(__file__).parent.parent

bb              = load_module(SCRIPTS / '_bitbucket.py',      '_bitbucket')
mine_feedback   = load_module(SCRIPTS / 'mine_feedback.py',   'mine_feedback')
check_resolved  = load_module(SCRIPTS / 'check_resolved.py',  'check_resolved')
check_dismissals= load_module(SCRIPTS / 'check_dismissals.py','check_dismissals')
check_replies   = load_module(SCRIPTS / 'check_replies.py',   'check_replies')
update_resolved = load_module(SCRIPTS / 'update_resolved.py', 'update_resolved')
update_card     = load_module(SCRIPTS / 'update_card_status.py', 'update_card_status')
aggregate_stats = load_module(SCRIPTS / 'aggregate_stats.py', 'aggregate_stats')
post_reply      = load_module(SCRIPTS / 'post_reply.py',      'post_reply')
ai_review       = load_module(BIN / 'ai-review',              'ai_review')
scan_diff       = load_module(SCRIPTS / 'scan_diff.py',        'scan_diff')
build           = load_module(REPO_ROOT / 'build.py',         'build')


def _fake_completed(stdout: str, returncode: int = 0):
    """Build a fake subprocess.CompletedProcess for mocking curl invocations."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr='',
    )


# ── _bitbucket helpers ─────────────────────────────────────────────────────────

class TestBitbucketHelpers(unittest.TestCase):

    def test_load_target_missing(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            self.assertIsNone(bb.load_target())

    def test_load_target_valid(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            os.makedirs('.ai-review')
            data = {'branch': 'feature/x', 'pr_id': 42, 'worktree_path': '/tmp/x'}
            Path('.ai-review/target.json').write_text(json.dumps(data))
            self.assertEqual(bb.load_target(), data)

    def test_load_target_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            os.makedirs('.ai-review')
            Path('.ai-review/target.json').write_text('{not json}')
            self.assertIsNone(bb.load_target())

    def test_get_branch_from_target(self):
        self.assertEqual(bb.get_branch({'branch': 'feature/pay', 'pr_id': 7}),
                         'feature/pay')

    def test_get_branch_empty_target(self):
        self.assertEqual(bb.get_branch({}), '')

    def test_get_creds_missing(self):
        os.environ.pop('BITBUCKET_EMAIL', None)
        os.environ.pop('BITBUCKET_API_TOKEN', None)
        self.assertIsNone(bb.get_creds())

    def test_get_creds_present(self):
        os.environ['BITBUCKET_EMAIL']     = 'a@b.com'
        os.environ['BITBUCKET_API_TOKEN'] = 'tok'
        self.assertEqual(bb.get_creds(), ('a@b.com', 'tok'))
        del os.environ['BITBUCKET_EMAIL']
        del os.environ['BITBUCKET_API_TOKEN']


# ── bb_post_status / bb_post — status-aware POST ──────────────────────────────

class TestBbPostStatus(unittest.TestCase):

    def test_2xx_returns_status_and_parsed_body(self):
        fake = _fake_completed('{"id": 42}\n__HTTP__200', 0)
        with patch.object(bb.subprocess, 'run', return_value=fake):
            status, body = bb.bb_post_status('http://x', ('e', 't'), {})
        self.assertEqual(status, 200)
        self.assertEqual(body, {'id': 42})

    def test_201_returns_status_and_parsed_body(self):
        fake = _fake_completed('{"id": 7}\n__HTTP__201', 0)
        with patch.object(bb.subprocess, 'run', return_value=fake):
            status, body = bb.bb_post_status('http://x', ('e', 't'), {})
        self.assertEqual(status, 201)
        self.assertEqual(body, {'id': 7})

    def test_409_returns_status_and_error_body(self):
        fake = _fake_completed(
            '{"type":"error","error":{"message":"already resolved"}}\n__HTTP__409', 0
        )
        with patch.object(bb.subprocess, 'run', return_value=fake):
            status, body = bb.bb_post_status('http://x', ('e', 't'), {})
        self.assertEqual(status, 409)
        self.assertEqual(body, {'type': 'error', 'error': {'message': 'already resolved'}})

    def test_500_with_unparseable_body_returns_status_only(self):
        fake = _fake_completed('<html>500</html>\n__HTTP__500', 0)
        with patch.object(bb.subprocess, 'run', return_value=fake):
            status, body = bb.bb_post_status('http://x', ('e', 't'), {})
        self.assertEqual(status, 500)
        self.assertIsNone(body)

    def test_transport_failure_returns_zero(self):
        fake = _fake_completed('', 7)  # curl non-zero exit
        with patch.object(bb.subprocess, 'run', return_value=fake):
            status, body = bb.bb_post_status('http://x', ('e', 't'), {})
        self.assertEqual(status, 0)
        self.assertIsNone(body)

    def test_bb_post_wrapper_returns_body_on_2xx(self):
        fake = _fake_completed('{"id": 99}\n__HTTP__201', 0)
        with patch.object(bb.subprocess, 'run', return_value=fake):
            self.assertEqual(bb.bb_post('http://x', ('e', 't'), {}), {'id': 99})

    def test_bb_post_wrapper_returns_none_on_4xx(self):
        fake = _fake_completed('{"error":"x"}\n__HTTP__409', 0)
        with patch.object(bb.subprocess, 'run', return_value=fake):
            self.assertIsNone(bb.bb_post('http://x', ('e', 't'), {}))


# ── aggregate_stats — classify / parse_meta / parse_created_at ────────────────

import datetime as _dt


class TestAggregateStats(unittest.TestCase):

    NOW = _dt.datetime(2026, 6, 15, tzinfo=_dt.timezone.utc)

    def test_classify_resolved(self):
        body = 'x <!-- ai-review:resolved:abc123 --> y'
        self.assertEqual(aggregate_stats.classify(body, '2026-06-14T00:00:00Z', self.NOW),
                         'resolved')

    def test_classify_other_when_no_marker(self):
        self.assertEqual(aggregate_stats.classify('plain comment', '2026-06-14T00:00:00Z', self.NOW),
                         'other')

    def test_classify_open_recent(self):
        body = '<!-- ai-review:open:abc123 -->'
        # created today → age 0 < STALE_DAYS
        self.assertEqual(aggregate_stats.classify(body, '2026-06-15T00:00:00Z', self.NOW),
                         'open')

    def test_classify_stale_after_threshold(self):
        body = '<!-- ai-review:open:abc123 -->'
        old = '2026-05-01T00:00:00Z'  # >14 days before NOW
        self.assertEqual(aggregate_stats.classify(body, old, self.NOW), 'stale')

    def test_parse_meta_valid(self):
        body = 'x <!-- ai-review:meta {"dim":"4b","severity":"warning"} --> y'
        self.assertEqual(aggregate_stats.parse_meta(body),
                         {'dim': '4b', 'severity': 'warning'})

    def test_parse_meta_absent(self):
        self.assertEqual(aggregate_stats.parse_meta('no meta here'), {})

    def test_parse_meta_invalid_json(self):
        self.assertEqual(aggregate_stats.parse_meta('<!-- ai-review:meta {bad} -->'), {})

    def test_parse_created_at_roundtrips_z_suffix(self):
        dt = aggregate_stats.parse_created_at('2026-06-15T12:00:00Z')
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.tzinfo, _dt.timezone.utc)

    def test_parse_created_at_bad_input_returns_now(self):
        # Non-fatal: bad timestamps fall back to "now" rather than crashing.
        dt = aggregate_stats.parse_created_at('not-a-date')
        self.assertIsInstance(dt, _dt.datetime)


# ── post_reply — anti-loop marker ─────────────────────────────────────────────

class TestPostReplyMarker(unittest.TestCase):

    def test_appends_marker_when_absent(self):
        out = post_reply.ensure_reply_marker('Thanks, dismissing this.')
        self.assertTrue(out.endswith(post_reply.REPLY_MARKER))
        self.assertIn('Thanks, dismissing this.', out)

    def test_idempotent_when_present(self):
        already = f'Body text\n\n{post_reply.REPLY_MARKER}'
        self.assertEqual(post_reply.ensure_reply_marker(already), already)

    def test_no_double_marker(self):
        out = post_reply.ensure_reply_marker(f'x {post_reply.REPLY_MARKER}')
        self.assertEqual(out.count(post_reply.REPLY_MARKER), 1)


# ── update_card_status — ticket extraction ────────────────────────────────────

class TestUpdateCardStatus(unittest.TestCase):

    def test_extract_from_feature_branch(self):
        self.assertEqual(
            update_card.extract_ticket_id('feature/B20-11233-add-stats-to-dashboards'),
            'B20-11233',
        )

    def test_extract_from_bugfix_branch(self):
        self.assertEqual(
            update_card.extract_ticket_id('bugfix/PROJ-42-fix-the-thing'),
            'PROJ-42',
        )

    def test_extract_from_pr_title(self):
        self.assertEqual(
            update_card.extract_ticket_id('B20-11233 - Add listing logic report'),
            'B20-11233',
        )

    def test_extract_first_match_when_multiple(self):
        # Only the first JIRA-style key should be returned.
        self.assertEqual(
            update_card.extract_ticket_id('B20-1 then later XYZ-99'),
            'B20-1',
        )

    def test_extract_returns_none_for_master(self):
        self.assertIsNone(update_card.extract_ticket_id('master'))

    def test_extract_returns_none_for_empty(self):
        self.assertIsNone(update_card.extract_ticket_id(''))
        self.assertIsNone(update_card.extract_ticket_id(None))

    def test_extract_ignores_lowercase_prefix(self):
        # Convention is uppercase prefix; `feat-123` shouldn't be picked up as a ticket.
        self.assertIsNone(update_card.extract_ticket_id('feat-123-something'))

    # ── ticket detection in CI/target mode ────────────────────────────────────

    def test_ticket_from_target_json_beats_git(self):
        # Target mode (CI) runs in a DETACHED worktree — git yields no branch;
        # the ticket must come from .ai-review/target.json.
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            os.makedirs('.ai-review')
            Path('.ai-review/target.json').write_text(
                json.dumps({'branch': 'bugfix/B20-11777-jpg-option', 'pr_id': 9}))
            os.environ.pop('BITBUCKET_BRANCH', None)
            self.assertEqual(update_card.detect_ticket(), 'B20-11777')

    def test_ticket_from_bitbucket_branch_env(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)  # no target.json, not a git repo
            os.environ['BITBUCKET_BRANCH'] = 'feature/B20-42-thing'
            try:
                self.assertEqual(update_card.detect_ticket(), 'B20-42')
            finally:
                del os.environ['BITBUCKET_BRANCH']

    def test_ticket_none_when_no_sources(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)  # no target.json, no env, not a git repo
            os.environ.pop('BITBUCKET_BRANCH', None)
            self.assertIsNone(update_card.detect_ticket())

    # ── source-status guard ───────────────────────────────────────────────────

    def test_parse_statuses_splits_and_trims(self):
        self.assertEqual(
            update_card.parse_statuses('Code Review, Failed Code Review'),
            ['Code Review', 'Failed Code Review'])

    def test_parse_statuses_empty_and_blanks(self):
        self.assertEqual(update_card.parse_statuses(''), [])
        self.assertEqual(update_card.parse_statuses(' , ,'), [])

    def test_eligible_source_case_insensitive(self):
        sources = ['Code Review', 'Failed Code Review']
        self.assertTrue(update_card.is_eligible_source('code review', sources))
        self.assertTrue(update_card.is_eligible_source('FAILED CODE REVIEW', sources))

    def test_ineligible_source_left_alone(self):
        sources = ['Code Review', 'Failed Code Review']
        for status in ('In Progress', 'Ready To Test', 'Done', 'To Do', ''):
            self.assertFalse(update_card.is_eligible_source(status, sources))


# ── update_resolved — body rewriting ──────────────────────────────────────────

class TestUpdateResolvedBody(unittest.TestCase):

    def test_replaces_open_marker_with_resolved(self):
        original = 'Original finding\n\n<!-- ai-review:open:abc123def456 -->\n\nmore text'
        with patch.object(update_resolved, 'get_commit_subject', return_value='Fix the bug'):
            result = update_resolved.build_resolved_body(original, 'fix1234abcdef')

        self.assertIn('✅ **Addressed in `fix1234`**', result)
        self.assertIn('— Fix the bug', result)
        self.assertIn('<!-- ai-review:resolved:fix1234abcdef -->', result)
        # Open marker must not survive.
        self.assertNotIn('ai-review:open:', result)
        # Original prose preserved.
        self.assertIn('Original finding', result)
        self.assertIn('more text', result)

    def test_handles_body_without_open_marker(self):
        original = 'Some finding with no marker at all'
        with patch.object(update_resolved, 'get_commit_subject', return_value=''):
            result = update_resolved.build_resolved_body(original, 'fix1234abcdef')

        # Empty subject → no `— subject` tail on the banner line.
        first_line = result.split('\n', 1)[0]
        self.assertEqual(first_line, '✅ **Addressed in `fix1234`**')
        self.assertIn('Some finding with no marker at all', result)
        self.assertIn('<!-- ai-review:resolved:fix1234abcdef -->', result)


# ── check_resolved — marker parsing ───────────────────────────────────────────

class TestCheckResolved(unittest.TestCase):

    def test_extract_open_sha_present(self):
        body = 'text <!-- ai-review:open:abc123def456 --> more'
        self.assertEqual(check_resolved.extract_open_sha(body), 'abc123def456')

    def test_extract_open_sha_absent(self):
        self.assertIsNone(check_resolved.extract_open_sha('no marker here'))

    def test_extract_open_sha_resolved_not_matched(self):
        self.assertIsNone(check_resolved.extract_open_sha('<!-- ai-review:resolved:x -->'))

    def test_is_already_resolved_true(self):
        self.assertTrue(check_resolved.is_already_resolved(
            'text <!-- ai-review:resolved:abc123 --> more'))

    def test_is_already_resolved_false(self):
        self.assertFalse(check_resolved.is_already_resolved(
            '<!-- ai-review:open:abc123 -->'))

    def test_extract_problem_standard(self):
        body = ('## 1. The problem\n'
                'Service accepts a raw array instead of a DTO.\n'
                '\n## 2. Why it matters\nmore')
        result = check_resolved.extract_problem(body)
        self.assertIn('raw array', result)
        self.assertNotIn('## 2.', result)

    def test_extract_problem_missing(self):
        self.assertEqual(check_resolved.extract_problem('no problem section'), '')


# ── check_resolved — posted-findings index (dedup source) ─────────────────────

class TestCheckResolvedPostedIndex(unittest.TestCase):

    def _comment(self, cid, path, line, body):
        return {'id': cid, 'inline': {'path': path, 'to': line},
                'content': {'raw': body}}

    def test_is_finding_open_and_resolved(self):
        self.assertTrue(check_resolved.is_finding('x <!-- ai-review:open:abc123 -->'))
        self.assertTrue(check_resolved.is_finding('x <!-- ai-review:resolved:abc123 -->'))

    def test_is_finding_excludes_replies_and_plain(self):
        self.assertFalse(check_resolved.is_finding('reply <!-- ai-review:reply -->'))
        self.assertFalse(check_resolved.is_finding('fixer <!-- ai-fixer:reply -->'))
        self.assertFalse(check_resolved.is_finding('a plain developer comment'))

    def test_is_dismissed(self):
        self.assertTrue(check_resolved.is_dismissed('<!-- ai-review:dismissed {"dim":"3a"} -->'))
        self.assertFalse(check_resolved.is_dismissed('<!-- ai-review:open:abc -->'))

    def test_extract_meta_valid_absent_invalid(self):
        self.assertEqual(
            check_resolved.extract_meta('<!-- ai-review:meta {"dim":"3a","severity":"🔴"} -->'),
            {'dim': '3a', 'severity': '🔴'})
        self.assertEqual(check_resolved.extract_meta('no meta'), {})
        self.assertEqual(check_resolved.extract_meta('<!-- ai-review:meta {bad} -->'), {})

    def test_build_posted_index_includes_open_and_resolved(self):
        comments = [
            self._comment(1, 'app/A.php', 10,
                'finding\n<!-- ai-review:meta {"dim":"3a","severity":"🔴"} -->\n'
                '<!-- ai-review:open:abc123 -->'),
            self._comment(2, 'app/B.php', 20,
                '✅ Addressed\n<!-- ai-review:meta {"dim":"1c","severity":"🟡"} -->\n'
                '<!-- ai-review:resolved:def456 -->'),
        ]
        idx = check_resolved.build_posted_index(comments)
        self.assertEqual(len(idx), 2)
        self.assertEqual(idx[0], {'comment_id': 1, 'path': 'app/A.php', 'line': 10,
                                  'dim': '3a', 'severity': '🔴', 'resolved': False})
        self.assertEqual(idx[1]['resolved'], True)
        self.assertEqual(idx[1]['dim'], '1c')

    def test_build_posted_index_excludes_dismissed_and_replies(self):
        comments = [
            self._comment(1, 'app/A.php', 10,
                          '❌ Dismissed\n<!-- ai-review:dismissed {"dim":"3a"} -->'),
            self._comment(2, 'app/A.php', 11, 'a reply <!-- ai-review:reply -->'),
            self._comment(3, 'app/A.php', 12, 'plain human comment'),
        ]
        self.assertEqual(check_resolved.build_posted_index(comments), [])

    def test_build_posted_index_missing_meta_yields_empty_dim(self):
        comments = [self._comment(1, 'app/A.php', 10,
                                  'legacy finding\n<!-- ai-review:open:abc123 -->')]
        idx = check_resolved.build_posted_index(comments)
        self.assertEqual(idx[0]['dim'], '')
        self.assertEqual(idx[0]['path'], 'app/A.php')


# ── mine_feedback — finding lifecycle classification ──────────────────────────

class TestMineFeedback(unittest.TestCase):

    def test_classify_open(self):
        state, meta = mine_feedback.classify_finding(
            'f\n<!-- ai-review:meta {"dim":"4b","severity":"🟡"} -->\n<!-- ai-review:open:abc -->')
        self.assertEqual(state, 'open')
        self.assertEqual(meta['dim'], '4b')

    def test_classify_resolved(self):
        state, _ = mine_feedback.classify_finding(
            '✅ fixed\n<!-- ai-review:resolved:def456 -->')
        self.assertEqual(state, 'resolved')

    def test_classify_dismissed_wins_and_carries_reason(self):
        # A dismissed body still contains the original text; dismissed must win.
        state, meta = mine_feedback.classify_finding(
            '❌ Dismissed\n<!-- ai-review:dismissed {"dim":"3a","reason":"internal endpoint"} -->')
        self.assertEqual(state, 'dismissed')
        self.assertEqual(meta['reason'], 'internal endpoint')

    def test_classify_non_finding_returns_none(self):
        self.assertIsNone(mine_feedback.classify_finding('a reply <!-- ai-review:reply -->'))
        self.assertIsNone(mine_feedback.classify_finding('plain human comment'))

    def test_aggregate_groups_by_dim_and_collects_reasons(self):
        dims = mine_feedback.aggregate([
            {'dim': '4b', 'state': 'resolved'},
            {'dim': '4b', 'state': 'dismissed', 'reason': 'reference table, bounded'},
            {'dim': '3a', 'state': 'open'},
        ])
        self.assertEqual(dims['4b']['posted'], 2)
        self.assertEqual(dims['4b']['resolved'], 1)
        self.assertEqual(dims['4b']['dismissal_reasons'], ['reference table, bounded'])
        self.assertEqual(dims['3a']['open'], 1)


# ── check_dismissals — dismissal parsing ──────────────────────────────────────

class TestCheckDismissals(unittest.TestCase):

    def test_parse_dismissal_valid(self):
        meta = {'path': 'app/Foo.php', 'line': 42, 'dim': '3a', 'reason': 'ok'}
        body = f'text <!-- ai-review:dismissed {json.dumps(meta)} -->'
        self.assertEqual(check_dismissals.parse_dismissal(body), meta)

    def test_parse_dismissal_absent(self):
        self.assertIsNone(check_dismissals.parse_dismissal('normal comment'))

    def test_parse_dismissal_invalid_json(self):
        self.assertIsNone(
            check_dismissals.parse_dismissal('<!-- ai-review:dismissed {bad} -->'))


# ── check_replies — author detection & thread state ──────────────────────────

class TestCheckReplies(unittest.TestCase):

    def test_is_ai_comment_open_marker(self):
        self.assertTrue(check_replies.is_ai_comment(
            'A finding.\n<!-- ai-review:open:abc123 -->'))

    def test_is_ai_comment_reply_marker(self):
        self.assertTrue(check_replies.is_ai_comment(
            "You're right, dismissing.\n\n<!-- ai-review:reply -->"))

    def test_is_ai_comment_human_reply(self):
        # A developer reply carries no marker, even when it disagrees.
        self.assertFalse(check_replies.is_ai_comment(
            "This is a false positive — auth is in the middleware."))

    def test_is_resolved_or_dismissed_true(self):
        self.assertTrue(check_replies.is_resolved_or_dismissed(
            '<!-- ai-review:resolved:abc123 -->'))
        self.assertTrue(check_replies.is_resolved_or_dismissed(
            '<!-- ai-review:dismissed {"reason":"x"} -->'))

    def test_is_resolved_or_dismissed_open(self):
        self.assertFalse(check_replies.is_resolved_or_dismissed(
            '<!-- ai-review:open:abc123 -->'))

    def test_extract_open_sha(self):
        self.assertEqual(
            check_replies.extract_open_sha('x <!-- ai-review:open:deadbeef --> y'),
            'deadbeef')

    def test_author_name_fallback(self):
        self.assertEqual(check_replies.author_name({}), 'developer')
        self.assertEqual(
            check_replies.author_name({'user': {'display_name': 'Jane'}}), 'Jane')


# ── ai-review bin — diff extraction ───────────────────────────────────────────

class TestAiReviewBin(unittest.TestCase):

    def test_extract_diff_present(self):
        body = 'text\n```diff\n-old\n+new\n```\nmore'
        self.assertEqual(ai_review.extract_diff(body), '-old\n+new')

    def test_extract_diff_absent(self):
        self.assertIsNone(ai_review.extract_diff('no diff block'))

    def test_extract_prompt_present(self):
        body = '```prompt\nFix the null dereference\n```'
        self.assertEqual(ai_review.extract_prompt(body), 'Fix the null dereference')

    def test_extract_prompt_absent(self):
        self.assertEqual(ai_review.extract_prompt('no prompt block'), '')

    def test_line_signature_stable(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.php', delete=False) as f:
            f.write('line1\nline2\nline3\nline4\nline5\n')
            name = f.name
        try:
            sig1 = ai_review.line_signature(name, 3)
            sig2 = ai_review.line_signature(name, 3)
            self.assertEqual(sig1, sig2)
            self.assertEqual(len(sig1), 12)
        finally:
            os.unlink(name)

    def test_line_signature_changes_with_content(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.php', delete=False) as f:
            f.write('line1\nline2\nline3\n')
            name = f.name
        try:
            sig_before = ai_review.line_signature(name, 2)
            Path(name).write_text('line1\nCHANGED\nline3\n')
            sig_after  = ai_review.line_signature(name, 2)
            self.assertNotEqual(sig_before, sig_after)
        finally:
            os.unlink(name)

    def test_line_signature_missing_file(self):
        self.assertEqual(ai_review.line_signature('/no/such/file.php', 5), '')

    # ── curl_post_status — /resolve on dismiss ────────────────────────────────

    def test_curl_post_status_2xx(self):
        for code in ('200', '201'):
            fake = _fake_completed(f'{{"id":1}}\n__HTTP__{code}', 0)
            with patch.object(ai_review, 'run', return_value=fake):
                self.assertEqual(
                    ai_review.curl_post_status('http://x/resolve', ('e', 't'), {}),
                    int(code))

    def test_curl_post_status_409_already_resolved(self):
        fake = _fake_completed('{"error":"resolved"}\n__HTTP__409', 0)
        with patch.object(ai_review, 'run', return_value=fake):
            self.assertEqual(
                ai_review.curl_post_status('http://x/resolve', ('e', 't'), {}), 409)

    def test_curl_post_status_transport_failure_is_zero(self):
        fake = _fake_completed('', 7)  # no __HTTP__ marker in stdout
        with patch.object(ai_review, 'run', return_value=fake):
            self.assertEqual(
                ai_review.curl_post_status('http://x/resolve', ('e', 't'), {}), 0)


# ── scan_diff — ignore marker detection ───────────────────────────────────────

class TestScanDiffIgnoreMarkers(unittest.TestCase):

    def _write(self, suffix: str, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode='w', suffix=suffix,
                                        delete=False)
        f.write(content)
        f.close()
        return f.name

    def tearDown(self):
        scan_diff._FILE_CACHE.clear()

    def test_php_ignore_marker(self):
        name = self._write('.php',
            '$a = 1;\n// ai-review:ignore internal CLI\n$b = 2;\n')
        try:
            self.assertTrue(scan_diff.has_ignore_marker_above(name, 3))
        finally:
            os.unlink(name)

    def test_empty_reason_not_matched(self):
        name = self._write('.php', '$a = 1;\n// ai-review:ignore\n$b = 2;\n')
        try:
            self.assertFalse(scan_diff.has_ignore_marker_above(name, 3))
        finally:
            os.unlink(name)

    def test_marker_too_far_above(self):
        name = self._write('.php',
            '// ai-review:ignore reason\n' + '$x = 1;\n' * 5)
        try:
            self.assertFalse(scan_diff.has_ignore_marker_above(name, 7))
        finally:
            os.unlink(name)

    def test_blade_marker(self):
        name = self._write('.blade.php',
            '{{-- ai-review:ignore trusted value --}}\n{{ $unsafe }}\n')
        try:
            self.assertTrue(scan_diff.has_ignore_marker_above(name, 2))
        finally:
            os.unlink(name)

    def test_html_marker(self):
        name = self._write('.vue',
            '<!-- ai-review:ignore cms content -->\n<div v-html="x"></div>\n')
        try:
            self.assertTrue(scan_diff.has_ignore_marker_above(name, 2))
        finally:
            os.unlink(name)


# ── build.py — generated SKILL.md must stay in sync with its template ──────────

class TestBuildIdempotency(unittest.TestCase):
    """Guards against the single most damaging failure mode in this repo:
    a generated SKILL.md being hand-edited so it no longer matches its
    template + shared fragments. When that happens, the next `python3 build.py`
    silently discards the hand-edits. This test fails the moment the committed
    SKILL.md drifts from `expand(template)`."""

    def test_generated_skill_md_matches_template(self):
        for template, output in build.BUILDS:
            with self.subTest(output=output.name):
                expected = build.expand(template)
                actual   = output.read_text()
                self.assertEqual(
                    expected, actual,
                    f'\n{output.relative_to(REPO_ROOT)} is out of sync with '
                    f'{template.relative_to(REPO_ROOT)}.\n'
                    f'Edit the TEMPLATE (not the generated file), then run '
                    f'`python3 build.py` and commit the result.',
                )


# ── Shared files must stay identical across the two skills ────────────────────

class TestSharedFilesNoDrift(unittest.TestCase):
    """The two skills each ship their own copy of these files. They are meant
    to be byte-identical — a divergence is almost always an accidental edit to
    one copy. This guard fails the moment they drift.

    NOT listed here (intentionally per-skill, do not add them):
      - scripts/check_version.sh   — different update URL + messages
      - scripts/branch_summary.sh  — reviewer resolves a commit-SHA base for
                                      the checkpoint feature; fixer does not
    """

    SHARED = [
        'scripts/scan_diff.py',
    ]

    def test_shared_files_identical(self):
        for rel in self.SHARED:
            with self.subTest(file=rel):
                reviewer = REPO_ROOT / 'skill' / rel
                fixer    = REPO_ROOT / 'skill-fixer' / rel
                self.assertTrue(reviewer.exists(), f'missing: {reviewer}')
                self.assertTrue(fixer.exists(),    f'missing: {fixer}')
                self.assertEqual(
                    reviewer.read_text(), fixer.read_text(),
                    f'\nskill/{rel} and skill-fixer/{rel} have drifted.\n'
                    f'These must stay byte-identical — sync them (copy the '
                    f'intended version over the other).',
                )


# ── Reviewer ships a Windows .ps1 for every cross-platform shell script ───────

class TestReviewerWindowsParity(unittest.TestCase):
    """code-reviewer supports native Windows: each shell script the skill
    invokes has a matching PowerShell variant. If you add a new reviewer
    `.sh` that the skill runs, add its `.ps1` here too.

    (pint_changed / pest_for_changed are deliberately excluded — code-reviewer
    never runs Pint/Pest; CI does.)
    """

    PORTED = [
        'branch_summary', 'check_version', 'cleanup_target', 'get_checkpoint',
        'post_review', 'refresh_branch', 'save_reviewed_sha', 'setup_target',
    ]

    def test_each_ported_script_has_both_variants(self):
        scripts = REPO_ROOT / 'skill' / 'scripts'
        for name in self.PORTED:
            with self.subTest(script=name):
                self.assertTrue((scripts / f'{name}.sh').exists(),
                                f'missing skill/scripts/{name}.sh')
                self.assertTrue((scripts / f'{name}.ps1').exists(),
                                f'missing Windows variant skill/scripts/{name}.ps1')


# ── scan_diff — hybrid-recall rules ───────────────────────────────────────────

def _mkdiff(path: str, *added_lines: str) -> str:
    """Minimal unified diff adding the given lines to `path`."""
    body = '\n'.join('+' + l for l in added_lines)
    return (
        f'diff --git a/{path} b/{path}\n'
        f'--- a/{path}\n'
        f'+++ b/{path}\n'
        f'@@ -0,0 +{len(added_lines)} @@\n'
        f'{body}\n'
    )


class TestScanDiffHybridRules(unittest.TestCase):

    def rules_hit(self, diff_text):
        return {f.rule for f in scan_diff.scan_text(diff_text)}

    # scan_text is a pure function over the diff string
    def test_scan_text_exists_and_returns_findings(self):
        diff = _mkdiff('app/Services/Foo.php', '        dd($x);')
        hits = self.rules_hit(diff)
        self.assertIn('no-dd-dump-die', hits)

    # secret-literal (§3i)
    def test_secret_literal_aws_key(self):
        diff = _mkdiff('app/Services/S3.php', "$key = 'AKIAIOSFODNN7EXAMPLE';")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_private_key_block(self):
        diff = _mkdiff('config/keys.php', "'pem' => '-----BEGIN RSA PRIVATE KEY-----',")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_named_secret_assignment(self):
        diff = _mkdiff('app/Services/Pay.php',
                       "$apiSecret = 'sk_live_51Hx9aBcDeFgH1234567890';")
        self.assertIn('secret-literal', self.rules_hit(diff))

    def test_secret_literal_ignores_short_and_unnamed(self):
        diff = _mkdiff('app/Services/Pay.php', "$mode = 'live';")
        self.assertNotIn('secret-literal', self.rules_hit(diff))

    # select-star (§9)
    def test_select_star_quoted(self):
        diff = _mkdiff('app/Repositories/R.php', "->select('*')")
        self.assertIn('select-star', self.rules_hit(diff))

    def test_select_star_db_raw(self):
        diff = _mkdiff('app/Repositories/R.php', 'DB::raw("SELECT * FROM users")')
        self.assertIn('select-star', self.rules_hit(diff))

    def test_select_columns_not_flagged(self):
        diff = _mkdiff('app/Repositories/R.php', "->select(['id', 'name'])")
        self.assertNotIn('select-star', self.rules_hit(diff))

    # get-then-pluck (§9)
    def test_get_then_pluck(self):
        diff = _mkdiff('app/Repositories/R.php', "$ids = $q->get()->pluck('id');")
        self.assertIn('get-then-pluck', self.rules_hit(diff))

    def test_builder_pluck_not_flagged(self):
        diff = _mkdiff('app/Repositories/R.php', "$ids = $q->pluck('id');")
        self.assertNotIn('get-then-pluck', self.rules_hit(diff))

    # log-getmessage (§10)
    def test_log_getmessage(self):
        diff = _mkdiff('app/Services/S.php', 'Log::error($e->getMessage());')
        self.assertIn('log-getmessage', self.rules_hit(diff))

    def test_log_with_exception_context_not_flagged(self):
        diff = _mkdiff('app/Services/S.php',
                       "Log::error('charge failed', ['exception' => $e]);")
        self.assertNotIn('log-getmessage', self.rules_hit(diff))

    # exception-in-response (§3f)
    def test_exception_in_json_response(self):
        diff = _mkdiff('app/Http/Controllers/C.php',
                       "return response()->json(['error' => $e->getMessage()], 500);")
        self.assertIn('exception-in-response', self.rules_hit(diff))

    def test_exception_in_abort(self):
        diff = _mkdiff('app/Http/Controllers/C.php', 'abort(500, $e->getMessage());')
        self.assertIn('exception-in-response', self.rules_hit(diff))

    def test_reported_exception_not_flagged(self):
        diff = _mkdiff('app/Http/Controllers/C.php', 'report($e);')
        self.assertNotIn('exception-in-response', self.rules_hit(diff))

    # JS routing fix (§12)
    def test_console_log_in_plain_js(self):
        diff = _mkdiff('resources/js/store/modules/agents.js', "console.log(state);")
        self.assertIn('no-console-log', self.rules_hit(diff))

    def test_debugger_in_ts(self):
        diff = _mkdiff('resources/js/helpers/date.ts', 'debugger;')
        self.assertIn('no-debugger', self.rules_hit(diff))

    def test_vue_rules_still_apply_to_vue(self):
        diff = _mkdiff('resources/js/components/A.vue', '<div v-html="userBio">')
        self.assertIn('v-html', self.rules_hit(diff))

    def test_abort_if_exception_message(self):
        diff = _mkdiff('app/Http/Controllers/C.php',
                       'abort_if($failed, 500, $e->getMessage());')
        self.assertIn('exception-in-response', self.rules_hit(diff))

    def test_log_debug_getmessage(self):
        diff = _mkdiff('app/Services/S.php', 'Log::debug($e->getMessage());')
        self.assertIn('log-getmessage', self.rules_hit(diff))

    def test_log_concat_getmessage(self):
        diff = _mkdiff('app/Services/S.php',
                       "Log::error('sync failed: ' . $e->getMessage());")
        self.assertIn('log-getmessage', self.rules_hit(diff))

    def test_db_select_star(self):
        diff = _mkdiff('app/Repositories/R.php', 'DB::select("select * from users");')
        self.assertIn('select-star', self.rules_hit(diff))

    def test_select_raw_star(self):
        diff = _mkdiff('app/Repositories/R.php', '$q->selectRaw("SELECT * FROM x");')
        self.assertIn('select-star', self.rules_hit(diff))

    def test_add_event_listener_plain_js(self):
        diff = _mkdiff('resources/js/helpers/bus.js', "el.addEventListener('click', fn);")
        self.assertIn('add-event-listener', self.rules_hit(diff))

    def test_vue_only_rules_not_on_plain_js(self):
        diff = _mkdiff('resources/js/helpers/x.js', '<div v-html="user.bio">')
        self.assertNotIn('v-html', self.rules_hit(diff))

    def test_console_log_in_jsx(self):
        diff = _mkdiff('resources/js/components/A.jsx', 'console.log(props);')
        self.assertIn('no-console-log', self.rules_hit(diff))


if __name__ == '__main__':
    unittest.main()
