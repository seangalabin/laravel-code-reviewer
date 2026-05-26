#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
    console.log(`
code-fixer — Claude Code skill installer (developer fix skill)

Usage:
  npx @redhq/code-reviewer code-fixer              Install into current project
  npx @redhq/code-reviewer code-fixer [target]     Install into a specific directory

The code-fixer skill is the developer-facing companion to code-reviewer.
It runs the same 14-dimension analysis but skips the mode-selection prompt
and goes straight to an interactive fix loop on your local branch.
No Bitbucket credentials required — it never posts to Bitbucket.

After installing, run in Claude Code:
  /code-fixer

The skill analyzes the branch, prints a summary, runs pre-flight checks
(dirty tree, file cap), then walks through each issue asking [y/n/s/q].
`);
    process.exit(0);
}

const target = args[0] ? path.resolve(args[0]) : process.cwd();

if (!fs.existsSync(target)) {
    console.error(`ERROR: target directory '${target}' does not exist.`);
    process.exit(1);
}

const src  = path.join(__dirname, '..', 'skill-fixer');
const dest = path.join(target, '.claude', 'skills', 'code-fixer');

function copyDir(from, to) {
    fs.mkdirSync(to, { recursive: true });
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
        const srcPath  = path.join(from, entry.name);
        const destPath = path.join(to, entry.name);
        if (entry.isDirectory()) {
            copyDir(srcPath, destPath);
        } else {
            fs.copyFileSync(srcPath, destPath);
            // preserve executable bit for scripts
            const srcMode = fs.statSync(srcPath).mode;
            fs.chmodSync(destPath, srcMode | 0o111);
        }
    }
}

console.log(`Installing code-fixer skill into ${dest} ...`);
copyDir(src, dest);

console.log(`
✓ Installed to ${dest}

──────────────────────────────────────────────────
 Usage: open Claude Code and run /code-fixer
──────────────────────────────────────────────────
The skill will:
  1. Refuse to run on main, master, or develop
  2. Diff the current branch against develop
  3. Run the 14-dimension analysis
  4. Print a summary and walk you through fixes interactively

No Bitbucket credentials needed — fixes are applied locally only.
Applied fixes are logged to .ai-review/applied-{timestamp}.log
`);
