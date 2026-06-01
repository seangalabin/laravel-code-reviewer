"""
Unit tests for pure-logic functions in skill/scripts/ and skill/bin/.

Run:  python3 -m pytest tests/          (if pytest is available)
  or: python3 -m unittest discover tests
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
check_resolved  = load_module(SCRIPTS / 'check_resolved.py',  'check_resolved')
check_dismissals= load_module(SCRIPTS / 'check_dismissals.py','check_dismissals')
ai_review       = load_module(BIN / 'ai-review',              'ai_review')
scan_diff       = load_module(SCRIPTS / 'scan_diff.py',        'scan_diff')
build           = load_module(REPO_ROOT / 'build.py',         'build')


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
        'scripts/pint_changed.sh',
        'scripts/pest_for_changed.sh',
        'references/laravel_review_guide.md',
        'references/vue_review_guide.md',
        'references/coding_standards.md',
        'references/common_antipatterns.md',
        'references/code_review_checklist.md',
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


if __name__ == '__main__':
    unittest.main()
