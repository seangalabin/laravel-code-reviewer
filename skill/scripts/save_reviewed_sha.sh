#!/usr/bin/env bash
# save_reviewed_sha.sh — record the current HEAD SHA as the last-reviewed checkpoint.
# Written to .ai-review/last-reviewed-sha after every successful review run.
# Used by the --since-last-review flag to scope the next review to new commits only.

set -euo pipefail

mkdir -p .ai-review
git rev-parse HEAD > .ai-review/last-reviewed-sha
echo "  Checkpoint saved: $(git rev-parse --short HEAD)"
