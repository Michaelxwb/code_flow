'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const glob = require('../lib/glob');
const fm = require('../lib/frontmatter');
const files = require('../lib/fs');
const config = require('../lib/config');
const adapters = require('../lib/adapters');
const spec = require('../lib/spec');

function project(t) {
  const root = files.realpath(fs.mkdtempSync(path.join(os.tmpdir(), 'cf-v1-data-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, '.code-flow/specs/cli'), { recursive: true });
  fs.writeFileSync(path.join(root, '.code-flow/config.json'), JSON.stringify({ version: 1 }));
  return root;
}

test('glob handles zero/multiple directories and diagnoses unsupported patterns', () => {
  assert.ok(glob.matches('src/**/*.js', 'src/app.js'));
  assert.ok(glob.matches('src/**/*.js', 'src/a/b/app.js'));
  assert.equal(glob.matches('src/*.js', 'src/a/app.js'), false);
  assert.ok(glob.matches('**/a?.js', 'ab.js'));
  assert.throws(() => glob.compile('src/{a,b}.js'), /glob/i);
});

test('frontmatter round trips BOM, CRLF and unknown user metadata', () => {
  const raw = '\ufeff---\r\n{"status":"draft","owner":"me"}\r\n---\r\n# body\r\n';
  const parsed = fm.parse(raw);
  assert.equal(parsed.meta.owner, 'me');
  assert.equal(fm.stringify(parsed, parsed.meta), raw);
  assert.throws(() => fm.parse('---\nstatus: draft\n---\n'), /JSON/);
});

test('paths reject traversal, wrong case and symlink escape before writes', t => {
  const root = project(t);
  assert.throws(() => files.inside(root, '../outside'), /path/i);
  assert.throws(() => files.inside(root, 'C:\\outside'), /path/i);
  const other = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-v1-outside-'));
  t.after(() => fs.rmSync(other, { recursive: true, force: true }));
  fs.symlinkSync(other, path.join(root, 'escape'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => files.inside(root, 'escape/new.txt'), /path/i);
  assert.throws(() => files.inside(root, '.code-flow/Specs/new.md'), /case|path/i);
});

test('config resolves roots and rejects loose values and invalid glob', t => {
  const root = project(t);
  assert.equal(config.findRoot(path.join(root, '.code-flow/specs')), files.realpath(root));
  assert.equal(config.load(root).tests.jobs, 2);
  fs.writeFileSync(path.join(root, '.code-flow/config.json'), '{"version":1,"tests":{"jobs":"2"}}');
  assert.throws(() => config.load(root), /jobs/);
  fs.writeFileSync(path.join(root, '.code-flow/config.json'), '{"version":1,"paths":{"{x}":["cli/runtime"]}}');
  assert.throws(() => config.load(root), /glob/i);
});

test('config root search stops at a Git worktree boundary', t => {
  const root = project(t);
  const git = args => {
    const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  };
  git(['init', '-q']);
  git(['config', 'user.name', 'Fixture']);
  git(['config', 'user.email', 'fixture@example.invalid']);
  git(['add', '-A']); git(['commit', '-qm', 'baseline']);
  const worker = path.join(root, 'linked-worker');
  git(['worktree', 'add', '--detach', worker, 'HEAD']);
  t.after(() => {
    spawnSync('git', ['worktree', 'remove', '--force', worker], { cwd: root });
    spawnSync('git', ['worktree', 'prune'], { cwd: root });
  });
  fs.rmSync(path.join(worker, '.code-flow/config.json'));
  assert.throws(() => config.findRoot(worker), /project_missing|Run inside/);
  assert.equal(config.findRoot(root), files.realpath(root));
});

test('Codex config updates only the real features.hooks field', () => {
  const raw = [
    'developer_instructions = """',
    '[features]',
    'hooks = false',
    '"""',
    '',
    '[features]',
    'hooks = false',
    '',
    '[mcp_servers."fixture]one".env]',
    'hooks = "user-value"',
    ''
  ].join('\n');
  const result = adapters.codexConfig(raw);
  assert.match(result, /developer_instructions = """\n\[features\]\nhooks = false\n"""/);
  assert.match(result, /\[features\]\nhooks = true/);
  assert.match(result, /\[mcp_servers\."fixture\]one"\.env\]\nhooks = "user-value"/);
});

test('Codex config recognizes quoted, dotted and array-boundary TOML forms', () => {
  const quoted = adapters.codexConfig('[features]\n"hooks" = false\n');
  assert.match(quoted, /"hooks" = true/);
  assert.equal((quoted.match(/\[features\]/g) || []).length, 1);
  const literal = adapters.codexConfig("[features]\n'hooks' = false\n");
  assert.match(literal, /'hooks' = true/);
  const dotted = adapters.codexConfig('features.hooks = false # user\n');
  assert.equal(dotted, 'features.hooks = true # user\n');
  const array = adapters.codexConfig('[features]\nother = 1\n[[skills.config]]\nhooks = false\n');
  assert.match(array, /\[features\]\nhooks = true/);
  assert.match(array, /\[\[skills\.config\]\]\nhooks = false/);
  const quotedTable = adapters.codexConfig('["features"]\nhooks = false\n');
  assert.match(quotedTable, /\["features"\]\nhooks = true/);
  const unicodeKey = adapters.codexConfig('[features]\n"\\u0068ooks" = false\n');
  assert.match(unicodeKey, /"\\u0068ooks" = true/);
  const unicodeTable = adapters.codexConfig('["\\u0066eatures"]\nhooks = false\n');
  assert.match(unicodeTable, /\["\\u0066eatures"\]\nhooks = true/);
  const singleKey = adapters.codexConfig('["features.hooks"] = false\n');
  assert.match(singleKey, /\["features\.hooks"\] = false/);
  assert.match(singleKey, /\[features\]\nhooks = true/);
  const dottedOther = adapters.codexConfig('features.shell_tool = false\n');
  assert.match(dottedOther, /features\.shell_tool = false\nfeatures\.hooks = true/);
  assert.equal((dottedOther.match(/\[features\]/g) || []).length, 0);
  const nestedArray = adapters.codexConfig('[features]\nshell_tool = true\n[[skills.config]]\nitems = [\n  ["features"],\n]\n');
  assert.match(nestedArray, /\[features\]\nhooks = true/);
  assert.match(nestedArray, /\["features"\]/);
  const subtable = adapters.codexConfig('[profiles.review]\nfeatures = { shell_tool = true }\n');
  assert.match(subtable, /\[profiles\.review\]\nfeatures = \{ shell_tool = true \}/);
  assert.match(subtable, /\[features\]\nhooks = true/);
  assert.throws(() => adapters.codexConfig('features.shell_tool = [\n false\n]\n'), /Multi-line/);
  assert.throws(() => adapters.codexConfig('features.shell_tool = """\n false\n"""\n'), /Multi-line/);
  assert.throws(() => adapters.codexConfig('"features" = { hooks = false }\n'), /\[features\] table/);
  assert.throws(() => adapters.codexConfig("'features' = { hooks = false }\n"), /\[features\] table/);
});

test('Codex config ignores quoted feature examples inside multiline strings', () => {
  const raw = [
    'developer_instructions = """',
    '["features"]',
    'hooks = false',
    '"""',
    '',
    '[features]',
    'hooks = false',
    ''
  ].join('\n');
  const result = adapters.codexConfig(raw);
  assert.match(result, /developer_instructions = """\n\["features"\]\nhooks = false\n"""/);
  assert.match(result, /\[features\]\nhooks = true/);
});

test('Codex config accepts CRLF comments when updating features.hooks', () => {
  const result = adapters.codexConfig('[features]\r\nhooks = false # comment\r\n');
  assert.match(result, /hooks = true # comment\r\n/);
});

test('rule blocks preserve examples, ignore fenced fake rules and reject duplicate IDs', t => {
  const root = project(t);
  const file = path.join(root, '.code-flow/specs/cli/runtime.md');
  const text = '---\n{"description":"runtime","next_rule":3}\n---\n## Rules\n\n' +
    '- [RULE-001] Keep JSON.\n  More detail.\n\n  ~~~js\n  - [RULE-999] example only\n  ~~~\n\n' +
    '- [RULE-cli-safe-001] Use stderr.\n';
  fs.writeFileSync(file, text);
  const loaded = spec.load(root, 'cli/runtime');
  assert.equal(loaded.rules.length, 2);
  assert.ok(loaded.rules[0].text.includes('RULE-999'));
  assert.throws(() => spec.load(root, '../runtime'), /Spec|path/);
  fs.writeFileSync(file, text + '- [RULE-001] duplicate\n');
  assert.throws(() => spec.load(root, 'cli/runtime'), /duplicate/i);
});

test('atomic writes preserve concurrent edits and lock conflicts are explicit', async t => {
  const root = project(t);
  const file = path.join(root, 'user.md');
  files.atomicWrite(file, 'one', null);
  assert.throws(() => files.atomicWrite(file, 'two', 'stale'), /concurrent/i);
  assert.equal(fs.readFileSync(file, 'utf8'), 'one');
  await files.withLock(root, 'test', async () => {
    await assert.rejects(files.withLock(root, 'test', async () => {}), /lock/i);
  });
  await files.withLock(root, 'test', async () => files.atomicWrite(file, 'two', 'one'));
  assert.equal(fs.readFileSync(file, 'utf8'), 'two');
});
