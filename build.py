#!/usr/bin/env python3
"""
build.py — assemble SKILL.md files from templates + shared fragments.

Templates live alongside the skill directories (*.template.md) and reference
shared fragments via HTML include markers:

    <!-- include:src/review-lens.md -->

Run after editing any template or fragment:
    python3 build.py

Generated files (committed so Claude Code can read them):
    skill/SKILL.md
    skill-fixer/SKILL.md
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

BUILDS = [
    (ROOT / 'skill' / 'SKILL.template.md',        ROOT / 'skill' / 'SKILL.md'),
    (ROOT / 'skill-fixer' / 'SKILL.template.md',  ROOT / 'skill-fixer' / 'SKILL.md'),
]

INCLUDE_RE = re.compile(r'^<!-- include:(.+?) -->$')


def expand(template_path: Path) -> str:
    lines = []
    for raw in template_path.read_text().splitlines(keepends=True):
        m = INCLUDE_RE.match(raw.rstrip('\n'))
        if m:
            fragment = ROOT / m.group(1)
            if not fragment.exists():
                print(f'ERROR: fragment not found: {fragment}', file=sys.stderr)
                sys.exit(1)
            lines.append(fragment.read_text())
        else:
            lines.append(raw)
    return ''.join(lines)


def main() -> None:
    for template, output in BUILDS:
        content = expand(template)
        output.write_text(content)
        print(f'  ✓ {output.relative_to(ROOT)}  ({output.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
