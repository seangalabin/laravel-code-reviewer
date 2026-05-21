#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
    console.log(`
code-reviewer — Claude Code skill installer

Usage:
  npx @redhq/code-reviewer              Install into current project
  npx @redhq/code-reviewer [target]     Install into a specific directory

After installing, add to .claude/settings.local.json in the project:
  {
    "env": {
      "BITBUCKET_EMAIL": "your@email.com",
      "BITBUCKET_API_TOKEN": "your_api_token"
    }
  }

Create a Bitbucket API token (Pull requests: write scope) at:
  https://bitbucket.org/account/settings/personal-access-tokens/
`);
    process.exit(0);
}

const target = args[0] ? path.resolve(args[0]) : process.cwd();

if (!fs.existsSync(target)) {
    console.error(`ERROR: target directory '${target}' does not exist.`);
    process.exit(1);
}

const src  = path.join(__dirname, '..', 'skill');
const dest = path.join(target, '.claude', 'skills', 'code-reviewer');

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

console.log(`Installing code-reviewer skill into ${dest} ...`);
copyDir(src, dest);

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
