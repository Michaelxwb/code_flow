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
  const wrapped = head + '\nmodule.exports = { mergeClaudeMd, mergeSettingsJson, mergeHookEventArray, maskFencedCode, ensurePyYaml, installAdapterFile };\n';
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

const { mergeClaudeMd, mergeSettingsJson, maskFencedCode } = loadCliInternals();

function withTmp(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-merge-test-'));
  try { fn(dir); } finally { fs.rmSync(dir, { recursive: true, force: true }); }
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

// --- run ---

const tests = [
  testMergeClaudeMdAddsMissingSection,
  testMergeClaudeMdIgnoresFencedCodeHeadings,
  testMaskFencedCodePreservesOffsets,
  testMergeAddsNewEvent,
  testMergeAddsNewMatcherWithinExistingEvent,
  testMergeAddsNewCommandIntoExistingMatcher,
  testMergeNeverOverwritesUserCommand,
  testMergeIdempotent,
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
