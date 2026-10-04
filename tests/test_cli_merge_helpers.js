#!/usr/bin/env node
'use strict';

// Direct unit tests for the merge helpers in src/cli.js.
// We exercise mergeClaudeMd and mergeSettingsJson against fixture files written
// to a temp directory. Run via `node tests/test_cli_merge_helpers.js`.

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

// Pull internals from cli.js by re-requiring it once and grabbing the exports.
// cli.js currently doesn't export — so we use a lightweight re-implementation
// strategy: spawn node with the cli loaded but interrupt before runInit.
// Simpler path: just require the file as a module inside an eval wrapper that
// captures module-level functions via globalThis.
const CLI_PATH = path.resolve(__dirname, '..', 'src', 'cli.js');

function loadCliInternals() {
  const src = fs.readFileSync(CLI_PATH, 'utf8');
  // Strip the trailing arg-handling block so requiring doesn't run init / fail.
  const cut = src.indexOf('// --- CLI argument parsing ---');
  if (cut === -1) throw new Error('cli.js sentinel comment moved');
  const head = src.slice(0, cut);
  const wrapped = head + '\nmodule.exports = { mergeClaudeMd, mergeSettingsJson, mergeOpencodeJson, mergeCodexConfigToml, mergeHookEventArray, maskFencedCode, ensurePyYaml, installAdapterFile, RUNTIME_GITIGNORE, ensureRuntimeGitignore };\n';
  // Write the temp module alongside cli.js so its `require('../package.json')`
  // (and any other relative requires) resolves the same way the real cli.js does.
  const tmp = path.join(path.dirname(CLI_PATH), `.cli-internals-${process.pid}.js`);
  fs.writeFileSync(tmp, wrapped);
  try {
    delete require.cache[require.resolve(tmp)];
    return require(tmp);
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
  }
}

const { mergeClaudeMd, mergeSettingsJson, mergeOpencodeJson, mergeCodexConfigToml, maskFencedCode, RUNTIME_GITIGNORE, ensureRuntimeGitignore } = loadCliInternals();
function withTmp(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-merge-test-'));
  try { fn(dir); } finally { fs.rmSync(dir, { recursive: true, force: true }); }
}

// --- RUNTIME_GITIGNORE ---

function testRuntimeGitignoreMatchesCanonicalTemplate() {
  // npm never ships `.gitignore`, so cli.js embeds the list. Keep it identical
  // (module block order aside) to src/core/code-flow/.gitignore.
  const canonical = fs.readFileSync(
    path.resolve(__dirname, '..', 'src', 'core', 'code-flow', '.gitignore'), 'utf8'
  );
  const entries = (text) => text.split('\n').filter(l => l && !l.startsWith('#')).sort();
  assert.deepStrictEqual(
    entries(RUNTIME_GITIGNORE), entries(canonical),
    'embedded RUNTIME_GITIGNORE must match src/core/code-flow/.gitignore entries'
  );
  console.log('  ✓ RUNTIME_GITIGNORE matches canonical template');
}

function testEnsureRuntimeGitignoreCreatesAndExtends() {
  withTmp(dir => {
    const results = { created: [], merged: [], updated: [], skipped: [] };
    ensureRuntimeGitignore(dir, results);
    const ignore = path.join(dir, '.code-flow', '.gitignore');
    assert.ok(fs.existsSync(ignore), 'fresh project must get .gitignore');
    assert.ok(results.created.includes('.code-flow/.gitignore'), 'created reported');
    const text = fs.readFileSync(ignore, 'utf8');
    for (const entry of ['backups/', '.session-log.jsonl', 'worktrees/', '.verifier-cache.json']) {
      assert.ok(text.includes(entry), `missing entry: ${entry}`);
    }
    // 老项目：托管块缺条目，升级补齐；用户行不动。
    fs.writeFileSync(ignore, text.replace('backups/\n', '') + 'my-own-line\n');
    const upgrade = { created: [], merged: [], updated: [], skipped: [] };
    ensureRuntimeGitignore(dir, upgrade);
    const final = fs.readFileSync(ignore, 'utf8');
    assert.ok(final.includes('backups/'), 'missing managed entry restored');
    assert.ok(final.includes('my-own-line'), 'user line preserved');
    assert.ok(upgrade.merged.some(item => item.includes('.code-flow/.gitignore')), 'merge reported');
    // 无托管块的文件视为用户所有，不得改写。
    fs.writeFileSync(ignore, 'user-only\n');
    const noop = { created: [], merged: [], updated: [], skipped: [] };
    ensureRuntimeGitignore(dir, noop);
    assert.strictEqual(fs.readFileSync(ignore, 'utf8'), 'user-only\n');
  });
  console.log('  ✓ ensureRuntimeGitignore creates/extends managed block only');
}

// --- mergeClaudeMd ---

function testMergeClaudeMdAddsMissingSection() {
  withTmp(dir => {
    const src = path.join(dir, 'src.md');
    const dest = path.join(dir, 'dest.md');
    fs.writeFileSync(src, '# Title\n\n## Alpha\nA\n\n## Beta\nB\n');
    fs.writeFileSync(dest, '# Title\n\n## Alpha\nA\n');

    const added = mergeClaudeMd(src, dest);
    assert.deepStrictEqual(added, ['## Beta'], 'Beta should be detected as new');
    const merged = fs.readFileSync(dest, 'utf8');
    assert.ok(merged.includes('## Beta'), 'merged output must contain new section');
    assert.ok(merged.includes('## Alpha'), 'merged output must keep old section');
  });
  console.log('  ✓ mergeClaudeMd adds missing section');
}

function testMergeClaudeMdIgnoresFencedCodeHeadings() {
  // Headings inside ```...``` blocks must NOT be treated as sections.
  withTmp(dir => {
    const src = path.join(dir, 'src.md');
    const dest = path.join(dir, 'dest.md');
    fs.writeFileSync(src,
      '## Real\nreal body\n\n' +
      '```markdown\n## Fake Inside Code Block\n```\n\n' +
      '## After\nx\n'
    );
    fs.writeFileSync(dest, '## Real\nreal body\n\n## After\nx\n');

    const added = mergeClaudeMd(src, dest);
    // src has Real, ## Fake, After; but Fake is inside fenced code → should be invisible.
    // dest has Real, After. Diff should be empty.
    assert.deepStrictEqual(
      added, [],
      `expected no additions (Fake was in code block), got: ${JSON.stringify(added)}`
    );
  });
  console.log('  ✓ mergeClaudeMd ignores ## inside fenced code');
}

function testMaskFencedCodePreservesOffsets() {
  const text = '## A\n```\n## fake\n```\n## B\n';
  const masked = maskFencedCode(text);
  assert.strictEqual(masked.length, text.length, 'mask must preserve length');
  assert.ok(masked.includes('## A') && masked.includes('## B'), 'real headings preserved');
  assert.ok(!masked.includes('## fake'), 'fenced heading replaced');
  console.log('  ✓ maskFencedCode preserves byte offsets');
}

// --- mergeClaudeMd managed markers ---

function testMergeClaudeMdKeepsManagedStartMarker() {
  withTmp(dir => {
    const src = path.join(dir, 'src.md');
    const dest = path.join(dir, 'dest.md');
    fs.writeFileSync(src,
      '# Title\n\n' +
      '<!-- code-flow:spec-loading schema=1 start -->\n' +
      '## Spec Workflow\nrules here\n' +
      '<!-- code-flow:spec-loading schema=1 end -->\n'
    );
    fs.writeFileSync(dest, '# Title\n\n## Existing\nkeep me\n');

    const added = mergeClaudeMd(src, dest);
    assert.ok(added.includes('## Spec Workflow'), 'section should be merged');
    const merged = fs.readFileSync(dest, 'utf8');
    assert.ok(merged.includes('<!-- code-flow:spec-loading schema=1 start -->'),
      'start marker must be included with its section');
    assert.ok(merged.includes('<!-- code-flow:spec-loading schema=1 end -->'), 'end marker present');
    assert.ok(merged.includes('## Existing'), 'user section preserved');
  });
  console.log('  ✓ mergeClaudeMd keeps managed start marker');
}

function testMergeClaudeMdRepairsUnpairedEndMarker() {
  withTmp(dir => {
    const src = path.join(dir, 'src.md');
    const dest = path.join(dir, 'dest.md');
    fs.writeFileSync(src,
      '<!-- code-flow:spec-loading schema=1 start -->\n' +
      '## Spec Workflow\nrules here\n' +
      '<!-- code-flow:spec-loading schema=1 end -->\n'
    );
    // Simulates a project merged by the old buggy cli: heading + end, no start.
    fs.writeFileSync(dest,
      '# Title\n\n## Spec Workflow\nstale body\n<!-- code-flow:spec-loading schema=1 end -->\n'
    );

    const added = mergeClaudeMd(src, dest);
    const merged = fs.readFileSync(dest, 'utf8');
    assert.ok(added.some(item => item.includes('start marker')), `repair reported: ${JSON.stringify(added)}`);
    assert.ok(merged.includes('<!-- code-flow:spec-loading schema=1 start -->'),
      'start marker must be restored before the section heading');
    const headingAt = merged.indexOf('## Spec Workflow');
    const startAt = merged.indexOf('<!-- code-flow:spec-loading schema=1 start -->');
    assert.ok(startAt !== -1 && startAt < headingAt, 'start marker must precede its heading');
    // Idempotent: second merge reports nothing.
    const second = mergeClaudeMd(src, dest);
    assert.deepStrictEqual(second, [], 'repair must be idempotent');
  });
  console.log('  ✓ mergeClaudeMd repairs unpaired end marker');
}

function testMergeClaudeMdLeavesUserSectionsWithoutMarkersAlone() {
  withTmp(dir => {
    const src = path.join(dir, 'src.md');
    const dest = path.join(dir, 'dest.md');
    fs.writeFileSync(src, '## Alpha\nA\n');
    fs.writeFileSync(dest, '## Alpha\nA\nuser text\n');
    const added = mergeClaudeMd(src, dest);
    assert.deepStrictEqual(added, [], 'no markers → no repair');
    assert.ok(fs.readFileSync(dest, 'utf8').includes('user text'), 'user content untouched');
  });
  console.log('  ✓ mergeClaudeMd ignores marker-free files');
}

// --- mergeSettingsJson hook deep merge ---

function testMergeAddsNewEvent() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, JSON.stringify({
      hooks: {
        SessionStart: [{ hooks: [{ type: 'command', command: 'foo' }] }]
      }
    }));
    fs.writeFileSync(dest, JSON.stringify({ hooks: {} }));

    const added = mergeSettingsJson(src, dest);
    assert.deepStrictEqual(added, ['hook: SessionStart']);
    const result = JSON.parse(fs.readFileSync(dest, 'utf8'));
    assert.ok(result.hooks.SessionStart, 'new event copied');
  });
  console.log('  ✓ mergeSettingsJson adds new event');
}

function testMergeAddsNewMatcherWithinExistingEvent() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit|Write', hooks: [{ type: 'command', command: 'cmdA' }] },
          { matcher: 'Bash', hooks: [{ type: 'command', command: 'cmdB' }] }
        ]
      }
    }));
    fs.writeFileSync(dest, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit|Write', hooks: [{ type: 'command', command: 'cmdA' }] }
        ]
      }
    }));

    const added = mergeSettingsJson(src, dest);
    // Edit|Write matcher already present → no add. Bash matcher is new → add.
    assert.ok(added.length >= 1, 'expected at least one add');
    assert.ok(added.some(s => s.includes('Bash')), 'Bash matcher should be added');
    const result = JSON.parse(fs.readFileSync(dest, 'utf8'));
    assert.strictEqual(result.hooks.PreToolUse.length, 2, 'array now has 2 items');
  });
  console.log('  ✓ mergeSettingsJson adds new matcher within existing event');
}

function testMergeAddsNewCommandIntoExistingMatcher() {
  // Critical regression: src adds a NEW handler under an EXISTING matcher.
  // Old behavior dropped it silently.
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, JSON.stringify({
      hooks: {
        PreToolUse: [
          {
            matcher: 'Edit|Write',
            hooks: [
              { type: 'command', command: 'cmdA' },
              { type: 'command', command: 'cmdNEW' }
            ]
          }
        ]
      }
    }));
    fs.writeFileSync(dest, JSON.stringify({
      hooks: {
        PreToolUse: [
          {
            matcher: 'Edit|Write',
            hooks: [{ type: 'command', command: 'cmdA' }]
          }
        ]
      }
    }));

    const added = mergeSettingsJson(src, dest);
    assert.ok(added.length >= 1, 'expected new command to be detected');
    const result = JSON.parse(fs.readFileSync(dest, 'utf8'));
    const cmds = result.hooks.PreToolUse[0].hooks.map(h => h.command);
    assert.deepStrictEqual(
      cmds.sort(), ['cmdA', 'cmdNEW'].sort(),
      'old command preserved AND new command added'
    );
  });
  console.log('  ✓ mergeSettingsJson adds new command into existing matcher');
}

function testMergeNeverOverwritesUserCommand() {
  // User customizes one command — merge must NOT change it, but must add new ones.
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit', hooks: [{ type: 'command', command: 'official-v2' }] }
        ]
      }
    }));
    fs.writeFileSync(dest, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit', hooks: [{ type: 'command', command: 'user-custom' }] }
        ]
      }
    }));

    mergeSettingsJson(src, dest);
    const result = JSON.parse(fs.readFileSync(dest, 'utf8'));
    const cmds = result.hooks.PreToolUse[0].hooks.map(h => h.command);
    assert.ok(cmds.includes('user-custom'), 'user command must be preserved');
    assert.ok(cmds.includes('official-v2'), 'src command must be added');
  });
  console.log('  ✓ mergeSettingsJson never overwrites user command');
}

function testMergeReplacesRetiredManagedHookCommands() {
  // Old managed scripts (cf_inject_hook.py / cf_session_hook.py) no longer
  // exist; their hook entries must be replaced by the current managed command
  // instead of lingering forever.
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    const current = 'd=...; f="$d/.code-flow/scripts/cf_pre_tool_hook.py"; python3 "$f"';
    fs.writeFileSync(src, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit|Write|MultiEdit', hooks: [{ type: 'command', command: current }] }
        ]
      }
    }));
    fs.writeFileSync(dest, JSON.stringify({
      hooks: {
        PreToolUse: [
          { matcher: 'Edit|Write|MultiEdit', hooks: [
            { type: 'command', command: 'd=...; f="$d/.code-flow/scripts/cf_inject_hook.py"; python3 "$f"' },
            { type: 'command', command: 'user-own-hook' }
          ] }
        ]
      }
    }));

    const added = mergeSettingsJson(src, dest);
    const result = JSON.parse(fs.readFileSync(dest, 'utf8'));
    const cmds = result.hooks.PreToolUse[0].hooks.map(h => h.command);
    assert.ok(!cmds.some(c => c.includes('cf_inject_hook.py')), 'retired managed hook removed');
    assert.ok(cmds.includes('user-own-hook'), 'user hook preserved');
    assert.ok(cmds.includes(current), 'current managed hook added');
    assert.ok(added.some(s => s.includes('cf_inject_hook.py')), 'retired removal reported');
    // Idempotent second run
    const second = mergeSettingsJson(src, dest);
    assert.ok(!second.some(s => s.includes('-retired')), 'no repeat retired report');
  });
  console.log('  ✓ mergeSettingsJson replaces retired managed hooks');
}

function testMergeIdempotent() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    const payload = {
      hooks: {
        SessionStart: [{ hooks: [{ type: 'command', command: 'foo' }] }]
      }
    };
    fs.writeFileSync(src, JSON.stringify(payload));
    fs.writeFileSync(dest, JSON.stringify(payload));

    const added = mergeSettingsJson(src, dest);
    assert.deepStrictEqual(added, [], 'no diff → empty result');
  });
  console.log('  ✓ mergeSettingsJson is idempotent on identical content');
}

function testMergeCodexConfigTomlAddsMissingHookFlag() {
  withTmp(dir => {
    const src = path.join(dir, 'src.toml');
    const dest = path.join(dir, 'dest.toml');
    fs.writeFileSync(src, '# code-flow Codex adapter\n[features]\nhooks = true\n');
    fs.writeFileSync(dest, 'model = "user-model"\n\n[features]\ncustom_feature = true\n');

    const added = mergeCodexConfigToml(src, dest);
    assert.deepStrictEqual(added, ['features.hooks']);
    const result = fs.readFileSync(dest, 'utf8');
    assert.ok(result.includes('model = "user-model"'), 'top-level user config preserved');
    assert.ok(result.includes('custom_feature = true'), 'existing feature preserved');
    assert.ok(result.includes('hooks = true'), 'missing flag added');
  });
  console.log('  ✓ mergeCodexConfigToml adds missing hook flag');
}

function testMergeCodexConfigTomlCreatesFeaturesSection() {
  withTmp(dir => {
    const src = path.join(dir, 'src.toml');
    const dest = path.join(dir, 'dest.toml');
    fs.writeFileSync(src, '# code-flow Codex adapter\n[features]\nhooks = true\n');
    fs.writeFileSync(dest, 'model = "user-model"\napproval_policy = "on-request"\n');

    const added = mergeCodexConfigToml(src, dest);
    assert.deepStrictEqual(added, ['features.hooks']);
    const result = fs.readFileSync(dest, 'utf8');
    assert.ok(result.includes('model = "user-model"'), 'top-level config preserved');
    assert.ok(result.includes('[features]\nhooks = true'), 'features section created');
  });
  console.log('  ✓ mergeCodexConfigToml creates [features] section');
}

function testMergeCodexConfigTomlInsertsBeforeBlankLineAfterFeatures() {
  withTmp(dir => {
    const src = path.join(dir, 'src.toml');
    const dest = path.join(dir, 'dest.toml');
    fs.writeFileSync(src, '# code-flow Codex adapter\n[features]\nhooks = true\n');
    fs.writeFileSync(dest, '[features]\ncustom_feature = true\n\n[profiles.default]\nmodel = "x"\n');

    mergeCodexConfigToml(src, dest);
    const result = fs.readFileSync(dest, 'utf8');
    assert.ok(
      result.includes('[features]\ncustom_feature = true\nhooks = true\n\n[profiles.default]'),
      'hook flag should stay visually inside [features]'
    );
  });
  console.log('  ✓ mergeCodexConfigToml inserts before blank section gap');
}

function testMergeCodexConfigTomlMigratesDeprecatedHookAlias() {
  withTmp(dir => {
    const src = path.join(dir, 'src.toml');
    const dest = path.join(dir, 'dest.toml');
    fs.writeFileSync(src, '# code-flow Codex adapter\n[features]\nhooks = true\n');
    fs.writeFileSync(dest, '[features]\ncodex_hooks = true\ncustom_feature = true\n');

    const added = mergeCodexConfigToml(src, dest);
    assert.deepStrictEqual(added, ['features.hooks']);
    const result = fs.readFileSync(dest, 'utf8');
    assert.ok(result.includes('hooks = true'), 'deprecated alias migrated');
    assert.ok(!result.includes('codex_hooks = true'), 'deprecated alias removed');
    assert.ok(result.includes('custom_feature = true'), 'existing feature preserved');
  });
  console.log('  ✓ mergeCodexConfigToml migrates deprecated hook alias');
}

function testMergeCodexConfigTomlIsIdempotent() {
  withTmp(dir => {
    const src = path.join(dir, 'src.toml');
    const dest = path.join(dir, 'dest.toml');
    fs.writeFileSync(src, '# code-flow Codex adapter\n[features]\nhooks = true\n');
    fs.writeFileSync(dest, '[features]\nhooks = true\ncustom_feature = true\n');

    const added = mergeCodexConfigToml(src, dest);
    assert.deepStrictEqual(added, []);
  });
  console.log('  ✓ mergeCodexConfigToml is idempotent');
}

// --- mergeOpencodeJson (v1 `plugin` → v2 `plugins` migration) ---

function testMergeOpencodeMigratesLegacyPluginKey() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, '{"$schema": "https://opencode.ai/config.json"}\n');
    fs.writeFileSync(dest, '{"$schema": "https://opencode.ai/config.json", "plugin": [".opencode/plugins/code-flow", "my-pkg"], "model": "m"}\n');

    mergeOpencodeJson(src, dest);
    const cfg = JSON.parse(fs.readFileSync(dest, 'utf8'));
    assert.ok(!('plugin' in cfg), 'legacy v1 key removed');
    assert.deepStrictEqual(cfg.plugins, ['my-pkg'], 'user entry carried to plugins, local path dropped');
    assert.strictEqual(cfg.model, 'm', 'unrelated user config preserved');
  });
  console.log('  ✓ mergeOpencodeJson migrates legacy plugin key');
}

function testMergeOpencodeDropsLocalPluginEntry() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, '{"$schema": "https://opencode.ai/config.json"}\n');
    fs.writeFileSync(dest, '{"plugins": [".opencode/plugins/code-flow", "other"]}\n');

    mergeOpencodeJson(src, dest);
    const cfg = JSON.parse(fs.readFileSync(dest, 'utf8'));
    assert.deepStrictEqual(cfg.plugins, ['other'], 'auto-discovered local entry dropped');
  });
  console.log('  ✓ mergeOpencodeJson drops auto-discovered local plugin entry');
}

function testMergeOpencodeIsIdempotent() {
  withTmp(dir => {
    const src = path.join(dir, 'src.json');
    const dest = path.join(dir, 'dest.json');
    fs.writeFileSync(src, '{"$schema": "https://opencode.ai/config.json"}\n');
    fs.writeFileSync(dest, '{"$schema": "https://opencode.ai/config.json", "plugins": ["my-pkg"]}\n');

    const added = mergeOpencodeJson(src, dest);
    assert.deepStrictEqual(added, []);
  });
  console.log('  ✓ mergeOpencodeJson is idempotent');
}

// --- run ---

const tests = [
  testRuntimeGitignoreMatchesCanonicalTemplate,
  testEnsureRuntimeGitignoreCreatesAndExtends,
  testMergeClaudeMdAddsMissingSection,
  testMergeClaudeMdIgnoresFencedCodeHeadings,
  testMergeClaudeMdKeepsManagedStartMarker,
  testMergeClaudeMdRepairsUnpairedEndMarker,
  testMergeClaudeMdLeavesUserSectionsWithoutMarkersAlone,
  testMaskFencedCodePreservesOffsets,
  testMergeAddsNewEvent,
  testMergeAddsNewMatcherWithinExistingEvent,
  testMergeAddsNewCommandIntoExistingMatcher,
  testMergeNeverOverwritesUserCommand,
  testMergeReplacesRetiredManagedHookCommands,
  testMergeIdempotent,
  testMergeCodexConfigTomlAddsMissingHookFlag,
  testMergeCodexConfigTomlCreatesFeaturesSection,
  testMergeCodexConfigTomlInsertsBeforeBlankLineAfterFeatures,
  testMergeCodexConfigTomlMigratesDeprecatedHookAlias,
  testMergeCodexConfigTomlIsIdempotent,
  testMergeOpencodeMigratesLegacyPluginKey,
  testMergeOpencodeDropsLocalPluginEntry,
  testMergeOpencodeIsIdempotent,
];

console.log('Running cli.js merge helper tests...');
let failed = 0;
for (const t of tests) {
  try {
    t();
  } catch (e) {
    console.error(`  ✗ ${t.name}: ${e.message}`);
    failed++;
  }
}
if (failed > 0) {
  console.error(`\n${failed} test(s) failed.`);
  process.exit(1);
}
console.log(`\nAll ${tests.length} tests passed.`);
