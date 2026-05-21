#!/usr/bin/env python3
"""
Regenerates install.sh from the current skill files.

Run this whenever any skill file changes:
    python3 .claude/skills/code-reviewer/generate_installer.py
"""
import os, base64, stat

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = [
    "SKILL.md",
    "scripts/branch_summary.sh",
    "scripts/scan_diff.py",
    "scripts/pint_changed.sh",
    "scripts/pest_for_changed.sh",
    "scripts/post_review.sh",
    "references/code_review_checklist.md",
    "references/coding_standards.md",
    "references/common_antipatterns.md",
    "references/laravel_review_guide.md",
    "references/vue_review_guide.md",
]

HEADER = r"""#!/usr/bin/env bash
# code-reviewer — Claude Code skill installer
#
# Installs the code-reviewer Claude Code skill into any Laravel/Bitbucket project.
#
# Usage (local):
#   bash .claude/skills/code-reviewer/install.sh
#   bash .claude/skills/code-reviewer/install.sh /path/to/other-project
#
# Usage (remote, if hosted):
#   curl -fsSL <raw-url>/install.sh | bash
#   curl -fsSL <raw-url>/install.sh | bash -s -- /path/to/project

set -euo pipefail

TARGET="${1:-.}"
SKILL="$TARGET/.claude/skills/code-reviewer"

if [[ ! -d "$TARGET" ]]; then
    echo "ERROR: target directory '$TARGET' does not exist." >&2
    exit 1
fi

echo "Installing code-reviewer skill into $SKILL ..."
mkdir -p "$SKILL/scripts" "$SKILL/references"

"""

FOOTER = r"""
chmod +x "$SKILL/scripts/branch_summary.sh" \
         "$SKILL/scripts/scan_diff.py" \
         "$SKILL/scripts/pint_changed.sh" \
         "$SKILL/scripts/pest_for_changed.sh" \
         "$SKILL/scripts/post_review.sh"

echo ""
echo "✓ Installed to $SKILL"
echo ""
echo "──────────────────────────────────────────────────"
echo " One-time setup: add to .claude/settings.local.json"
echo "──────────────────────────────────────────────────"
cat <<'SETUP'
{
  "env": {
    "BITBUCKET_EMAIL": "your@email.com",
    "BITBUCKET_API_TOKEN": "your_api_token"
  }
}
SETUP
echo ""
echo "Create a Bitbucket API token (Pull requests: write scope) at:"
echo "  https://bitbucket.org/account/settings/personal-access-tokens/"
"""


def main() -> None:
    lines = [HEADER]

    for f in FILES:
        path = os.path.join(SKILL_DIR, f)
        with open(path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode()
        lines.append(f"# {f}\n")
        lines.append(f"echo '{encoded}' | base64 -d > \"$SKILL/{f}\"\n\n")

    lines.append(FOOTER)

    out_path = os.path.join(SKILL_DIR, "install.sh")
    with open(out_path, "w") as fh:
        fh.write("".join(lines))

    os.chmod(out_path, os.stat(out_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"✓ Generated {out_path} ({os.path.getsize(out_path):,} bytes)")


if __name__ == "__main__":
    main()
