#!/usr/bin/env python3
"""
build.py — assemble SKILL.md files from templates + shared fragments.

Templates live alongside the skill directories (*.template.md) and reference
shared fragments via HTML include markers:

    <!-- include:src/review-lens.md -->    inline the fragment verbatim
    <!-- lensref:src/review-lens.md -->    ship the fragment as a SIBLING file and
                                           inline only a stub + dimension index

`lensref` exists for cost. The review lens is ~23k tokens — 65% of SKILL.md — and
everything in SKILL.md is loaded the moment the skill is invoked, on every run.
Most of that is waste: a run that stops at the version check, refuses a protected
branch, or finds no new commits since the checkpoint never walks the lens, yet
still pays for it. Worse in CI, where each container starts with a cold prompt
cache and the whole preamble is re-sent every turn of the agentic loop.

Shipping the lens as a sibling file the skill Reads at the lens-walk step keeps
the always-loaded preamble small and moves the lens cost onto the runs that
actually review a diff.

Run after editing any template or fragment:
    python3 build.py

Generated files (committed so Claude Code can read them):
    skill/SKILL.md              skill/review-lens.md
    skill-fixer/SKILL.md        skill-fixer/review-lens.md
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# (template, output SKILL.md, installed skill directory name)
BUILDS = [
    (ROOT / 'skill' / 'SKILL.template.md',        ROOT / 'skill' / 'SKILL.md',        'code-reviewer'),
    (ROOT / 'skill-fixer' / 'SKILL.template.md',  ROOT / 'skill-fixer' / 'SKILL.md',  'code-fixer'),
]

INCLUDE_RE = re.compile(r'^<!-- include:(.+?) -->$')
LENSREF_RE = re.compile(r'^<!-- lensref:(.+?) -->$')

LENS_FILENAME = 'review-lens.md'

# Top-level lens dimensions look like "### 1. Architecture & Layering (…)".
DIMENSION_RE = re.compile(r'^### (\d+)\.\s+(.*)$', re.M)


def lens_stub(fragment: Path, skill_name: str) -> str:
    """The text that replaces a lensref marker: pointer + dimension index.

    The index is generated from the fragment so it can never drift out of sync
    with the lens itself. It exists so the skill knows what the lens covers —
    and can name dimensions in the coverage ledger — without loading the rules.
    """
    text = fragment.read_text()
    dims = DIMENSION_RE.findall(text)
    if not dims:
        print(f'ERROR: no "### N. Title" dimensions found in {fragment}', file=sys.stderr)
        sys.exit(1)

    approx_tokens = round(len(text) / 4 / 1000)
    index = '\n'.join(f'| §{num} | {title.strip()} |' for num, title in dims)

    return f"""## Review lens

**The lens is not in this file.** It lives beside it, at
`.claude/skills/{skill_name}/{LENS_FILENAME}` (~{approx_tokens}k tokens), and you must
**Read it in full at the lens-walk step — and not before.**

This is deliberate, and it is about cost. Runs that stop early — version check,
protected-branch refusal, no new commits since the checkpoint — must never pay to load
rules they will not apply. Reading it earlier than the lens walk throws that saving away.

Two rules when you do read it:

- **Read the whole file, once.** Do not grep it for a few dimensions, and do not read it
  per-file or per-chunk — that re-pays the cost every time. One Read, then walk.
- **Never substitute the index below for the lens.** The table names the dimensions so you
  can build the coverage ledger; it contains none of the rules. A lens walk done off the
  index alone is not a review — if you have not Read the file, you cannot report coverage.

| Dim | Dimension |
|---|---|
{index}

---

"""


def expand(template_path: Path, skill_dir: Path, skill_name: str):
    """Render a template. Pure — returns what to write, writes nothing itself.

    Returns (skill_md_content, {path: content}) where the dict holds sidecar
    files the template asked to be shipped alongside SKILL.md. Keeping this
    side-effect-free is what lets the build-idempotency test compare the
    committed output against a fresh render without rewriting the tree.
    """
    lines = []
    sidecars = {}
    for raw in template_path.read_text().splitlines(keepends=True):
        stripped = raw.rstrip('\n')

        m = INCLUDE_RE.match(stripped)
        if m:
            lines.append(_fragment(m.group(1)).read_text())
            continue

        m = LENSREF_RE.match(stripped)
        if m:
            fragment = _fragment(m.group(1))
            # Ship the lens as a sibling of SKILL.md. install.js copies the skill
            # directory recursively, so it lands in the installed skill with no
            # change to the installer.
            sidecars[skill_dir / LENS_FILENAME] = fragment.read_text()
            lines.append(lens_stub(fragment, skill_name))
            continue

        lines.append(raw)
    return ''.join(lines), sidecars


def _fragment(rel: str) -> Path:
    path = ROOT / rel
    if not path.exists():
        print(f'ERROR: fragment not found: {path}', file=sys.stderr)
        sys.exit(1)
    return path


def main() -> None:
    for template, output, skill_name in BUILDS:
        content, sidecars = expand(template, output.parent, skill_name)
        for path, text in sidecars.items():
            path.write_text(text)
            print(f'  ✓ {path.relative_to(ROOT)}  ({len(text) // 1024} KB, read on demand)')
        output.write_text(content)
        size = output.stat().st_size
        print(f'  ✓ {output.relative_to(ROOT)}  ({size // 1024} KB, ~{size // 4000}k tokens always loaded)')


if __name__ == '__main__':
    main()
