#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const isFixer = args.includes('--skill=fixer');

if (args.includes('--help') || args.includes('-h')) {
    console.log(`
code-reviewer — Claude Code skill installer

Usage:
  npx github:seangalabin/laravel-code-reviewer                    Install code-reviewer (reviewer skill)
  npx github:seangalabin/laravel-code-reviewer --skill=fixer      Install code-fixer (developer skill)
  npx github:seangalabin/laravel-code-reviewer [target]           Install into a specific directory
  npx github:seangalabin/laravel-code-reviewer --skill=fixer [target]

Skills:
  (default)      code-reviewer — reviews a PR and posts inline comments to Bitbucket
  --skill=fixer  code-fixer    — reviews the branch and walks you through applying fixes locally

After installing code-reviewer, add to .claude/settings.local.json:
  {
    "env": {
      "BITBUCKET_EMAIL": "your@email.com",
      "BITBUCKET_API_TOKEN": "your_api_token"
    }
  }

code-fixer needs no credentials — it never posts to Bitbucket.
`);
    process.exit(0);
}

// Strip flag args to find the optional target path
const positional = args.filter(a => !a.startsWith('--'));
const target = positional[0] ? path.resolve(positional[0]) : process.cwd();

if (!fs.existsSync(target)) {
    console.error(`ERROR: target directory '${target}' does not exist.`);
    process.exit(1);
}

const skillName = isFixer ? 'code-fixer'    : 'code-reviewer';
const srcDir    = isFixer ? 'skill-fixer'   : 'skill';
const src       = path.join(__dirname, '..', srcDir);
const dest      = path.join(target, '.claude', 'skills', skillName);

function copyDir(from, to) {
    fs.mkdirSync(to, { recursive: true });
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
        const srcPath  = path.join(from, entry.name);
        const destPath = path.join(to, entry.name);
        if (entry.isDirectory()) {
            copyDir(srcPath, destPath);
        } else {
            fs.copyFileSync(srcPath, destPath);
            const srcMode = fs.statSync(srcPath).mode;
            fs.chmodSync(destPath, srcMode | 0o111);
        }
    }
}

console.log(`Installing ${skillName} skill into ${dest} ...`);
copyDir(src, dest);

// ── Write / merge allowedTools permissions ───────────────────────────────────
// These let the review scripts run without per-command confirmation prompts.
const allowedTools = isFixer
    ? [
        'Bash(.claude/skills/code-fixer/scripts/*)',
        'Bash(.claude/skills/code-fixer/bin/*)',
        'Bash(bash .claude/skills/code-fixer/scripts/*)',
        'Bash(git diff*)',
        'Bash(git log*)',
        'Bash(git branch*)',
        'Bash(git fetch*)',
        'Bash(git rev-parse*)',
        'Bash(npm run lint*)',
        'Bash(vendor/bin/pint*)',
        'Bash(vendor/bin/pest*)',
      ]
    : [
        'Bash(.claude/skills/code-reviewer/scripts/*)',
        'Bash(.claude/skills/code-reviewer/bin/*)',
        'Bash(bash .claude/skills/code-reviewer/scripts/*)',
        'Bash(git diff*)',
        'Bash(git log*)',
        'Bash(git branch*)',
        'Bash(git fetch*)',
        'Bash(git rev-parse*)',
        'Bash(git worktree*)',
        'Bash(git -C*)',
      ];

const settingsPath = path.join(target, '.claude', 'settings.json');
let settings = {};
if (fs.existsSync(settingsPath)) {
    try { settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8')); } catch (_) {}
}
settings.permissions               = settings.permissions               || {};
settings.permissions.allow         = settings.permissions.allow         || [];
for (const entry of allowedTools) {
    if (!settings.permissions.allow.includes(entry)) {
        settings.permissions.allow.push(entry);
    }
}
fs.mkdirSync(path.join(target, '.claude'), { recursive: true });
fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + '\n');

if (isFixer) {
    console.log(`
✓ Installed to ${dest}

──────────────────────────────────────────────────
 Usage: open Claude Code and run /code-fixer
──────────────────────────────────────────────────
The skill will:
  1. Refuse to run on main, master, or develop
  2. Diff the current branch against develop
  3. Run the 14-dimension analysis
  4. Walk you through fixes interactively [y/n/s/q]

No Bitbucket credentials needed — fixes are applied locally only.
Applied fixes are logged to .ai-review/applied-{timestamp}.log
`);
} else {
    console.log(`
✓ Installed to ${dest}

──────────────────────────────────────────────────
 One-time setup: add to .claude/settings.local.json
──────────────────────────────────────────────────
{
  "env": {
    "BITBUCKET_EMAIL": "your@email.com",
    "BITBUCKET_API_TOKEN": "your_api_token"
  }
}

Create a Bitbucket API token (Pull requests: write scope) at:
  https://bitbucket.org/account/settings/personal-access-tokens/
`);
}
