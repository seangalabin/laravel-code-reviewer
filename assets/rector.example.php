<?php

declare(strict_types=1);

/**
 * Rector config for the rules code-reviewer deliberately does NOT flag.
 *
 * The review lens used to carry nine §2 sub-rules that a tool can decide exactly:
 * strict_types, property types, casing, negated-if-with-else, redundant else after
 * return, deep nesting, nested ternaries, double negatives, and count()-for-emptiness.
 * Every one was a 🔵 Suggestion, and together they dominated comment volume — a
 * reviewer whose output is mostly style nits gets skimmed instead of read.
 *
 * They are gone from the lens. This config is where they live now. Rector is exact
 * where a reviewer is probabilistic: it never misses an instance, never invents one,
 * and it *fixes* rather than comments. Run it BEFORE the review step so the reviewer
 * only ever sees code that has already been through it.
 *
 * ── Setup ────────────────────────────────────────────────────────────────────
 *   composer require --dev rector/rector driftingly/rector-laravel
 *   cp vendor/redhq/code-reviewer/assets/rector.example.php rector.php
 *   vendor/bin/rector process --dry-run     # review first
 *   vendor/bin/rector process               # apply
 *
 * ── Honest scope note ────────────────────────────────────────────────────────
 * This covers most of what was removed, not all of it. Specifically:
 *   * strict_types, property types, redundant else, deep nesting / early return,
 *     count()-for-emptiness  → covered by the prepared sets below.
 *   * casing / formatting                                    → Pint already covers.
 *   * nested ternaries       → needs slevomat/coding-standard's
 *                              SlevomatCodingStandard.ControlStructures.DisallowNestedTernary
 *                              (a PHPCS sniff, not Rector). See phpstan.example.neon's
 *                              footer for the PHPCS wiring.
 *   * double negatives ($notReady tested as !$notReady)      → NO tool rule exists.
 *     This one is genuinely dropped coverage. It was a subjective 🔵 that produced
 *     more argument than value; if your team wants it back, add it to CLAUDE.md as a
 *     project rule and the reviewer will enforce it at the severity you state.
 *
 * The fluent methods used below are Rector's stable configuration API. Individual
 * rule FQCNs move between major versions, so this config deliberately names none —
 * if you want to pin specific rules, check them against your installed version.
 */

use Rector\Config\RectorConfig;

return RectorConfig::configure()
    ->withPaths([
        __DIR__ . '/app',
        __DIR__ . '/database',
        __DIR__ . '/routes',
        __DIR__ . '/tests',
    ])

    // Match the lens's own scope decision: the reviewer never asked for strict_types
    // in migrations, config, or route files, so don't let Rector rewrite them either.
    ->withSkip([
        __DIR__ . '/bootstrap/cache',
        __DIR__ . '/storage',
        __DIR__ . '/vendor',
    ])

    // Set your real PHP version. Without this Rector infers it from composer.json,
    // which is usually right but silently wrong if that constraint is loose.
    ->withPhpSets(php83: true)

    ->withPreparedSets(
        // deleted §2c — adds property/param/return types Rector can prove
        typeDeclarations: true,

        // deleted §2f (redundant else after return) and §2g (deep nesting):
        // inverts conditions into guard clauses so the happy path reads at base indent
        earlyReturn: true,

        // deleted §2m (count($x) > 0 → empty()/isNotEmpty()) plus a wide range of
        // other mechanical simplifications the lens never claimed
        codeQuality: true,

        // strict boolean comparisons — catches the truthiness sloppiness that made
        // the old §2l double-negative rule feel necessary in the first place
        strictBooleans: true,
    );

// ── deleted §2a — declare(strict_types=1) ────────────────────────────────────
//
// Not wired in above, on purpose. Two reasons:
//
// 1. The same warning the lens itself carried: adding the declaration changes
//    coercion semantics for the WHOLE file, not just the lines Rector touched. A
//    latent loose-type call elsewhere in a legacy file can start throwing at
//    runtime. Roll it out behind a green test suite, directory by directory —
//    never across a large legacy codebase in one commit.
//
// 2. Rector's rule for it (DeclareStrictTypesRector) has moved namespace between
//    major versions, so hardcoding the FQCN here would risk a config that will not
//    boot. Resolve it against your installed version:
//
//        vendor/bin/rector list-rules | grep -i strict
//
//    then add `->withRules([...])` with the FQCN that prints.
//
// Simplest option: skip Rector for this entirely. Pint's `declare_strict_types`
// rule does the same job, and you are already running Pint.
