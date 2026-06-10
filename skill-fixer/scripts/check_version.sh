#!/usr/bin/env bash
# Checks the installed skill version against the latest on GitHub.
# Exits 0 if current or GitHub unreachable. Exits 1 if outdated.

echo "🔍 Checking skill version..."

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$(cat "$SKILL_DIR/VERSION" 2>/dev/null | tr -d '[:space:]')"
REMOTE="$(curl -sSf --max-time 5 \
    https://raw.githubusercontent.com/seangalabin/laravel-code-reviewer/master/skill-fixer/VERSION \
    2>/dev/null | tr -d '[:space:]')"

if [[ -z "$REMOTE" ]]; then
    echo "  ↷ Could not reach GitHub — continuing with installed v${LOCAL:-unknown}."
    exit 0
fi

if [[ "$LOCAL" != "$REMOTE" ]]; then
    echo ""
    echo "⚠️  code-fixer is out of date (installed: ${LOCAL:-unknown}, latest: $REMOTE)."
    echo "   Update before continuing:"
    echo ""
    echo "     npx github:seangalabin/laravel-code-reviewer --skill=fixer"
    echo ""
    exit 1
fi

echo "  ✓ Up to date (v$LOCAL)"
exit 0
