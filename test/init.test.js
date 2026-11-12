'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync, spawn } = require('node:child_process');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const h = require('./helpers');
const init = require('../lib/init');
const adapters = require('../lib/adapters');
const f = require('../lib/fs');
function empty(t) {
  const root = f.realpath(fs.mkdtempSync(path.join(os.tmpdir(), 'cf-v1-init-')));
  t.after(() => { fs.rmSync(f.transientRoot(root), { recursive: true, force: true }); fs.rmSync(root, { recursive: true, force: true }); });
  return root;
}
test('fresh global init is idempotent and dry-run writes nothing', async t => {
  const root = empty(t);
  const dry = await init.init(root, { platform: 'codex', dryRun: true });
  assert.ok(dry.changes.length > 0); assert.deepEqual(fs.readdirSync(root), []);
  assert.equal(fs.existsSync(f.transientRoot(root)), false);
  await init.init(root, { platform: 'codex' });
  assert.equal((await init.init(root)).changes.length, 0);
  assert.equal(fs.existsSync(path.join(root, '.code-flow/scripts')), false);
  const names = fs.readdirSync(path.join(root, '.code-flow'));
  assert.deepEqual(names.sort(), ['config.json', 'launcher', 'specs', 'tasks', 'templates']);
  assert.ok(fs.existsSync(path.join(root, '.code-flow/templates/prd.md')));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/templates/task.md')));
  for (const name of ['bridge.cjs', 'hook.sh', 'hook.cmd', 'hook.ps1'])
    assert.ok(fs.existsSync(path.join(root, '.code-flow/launcher', name)), name);
});
test('init installs a project guidelines starter and cf-init references it', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  const starter = fs.readFileSync(path.join(root, '.code-flow/templates/project-guidelines.md'), 'utf8');
  assert.match(starter, /\.code-flow\/specs/);
  assert.match(starter, /next_rule/);
  const skill = fs.readFileSync(path.join(root, '.agents/skills/cf-init/SKILL.md'), 'utf8');
  assert.match(skill, /project-guidelines\.md/);
});

test('init overwrites tool templates but preserves user specs and tasks', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const task = h.task(root);
  h.write(root, '.code-flow/templates/prd.md', 'user template edit\n');
  fs.writeFileSync(path.join(root, task), 'user task content\n');
  await init.init(root);
  assert.notEqual(fs.readFileSync(path.join(root, '.code-flow/templates/prd.md'), 'utf8'), 'user template edit\n');
  assert.ok(fs.readFileSync(path.join(root, '.code-flow/specs/cli/runtime.md'), 'utf8').includes('Current rule.'));
  assert.equal(fs.readFileSync(path.join(root, task), 'utf8'), 'user task content\n');
});

test('init ignores brackets in comments on dotted feature values', async t => {
  for (const newline of ['\n', '\r\n']) {
    for (const comment of ['[user note', ']user note', '[user note]', '"[" user note']) {
      const root = empty(t);
      const raw = 'features.shell_tool = false # ' + comment + newline;
      const file = h.write(root, '.codex/config.toml', raw);
      assert.equal((await init.init(root, { platform: 'codex' })).ok, true);
      assert.equal(fs.readFileSync(file, 'utf8'), raw + 'features.hooks = true\n');
      assert.equal((await init.init(root)).changes.length, 0);
    }
  }
});

test('init reports multiline dotted arrays as a per-file conflict', async t => {
  for (const newline of ['\n', '\r\n']) {
    for (const comment of [']', ']]', '"]"', '# [ ] ]']) {
      const root = empty(t);
      const raw = ['features.custom = [ # ' + comment, ' "user-value"', ']', ''].join(newline);
      const file = h.write(root, '.codex/config.toml', raw);
      const result = await init.init(root, { platform: 'codex' });
      assert.equal(result.ok, false);
      assert.ok(result.conflicts.some(item => item.path === '.codex/config.toml' &&
        item.code === 'config_format' && /Multi-line/.test(item.message)));
      assert.equal(fs.readFileSync(file, 'utf8'), raw);
      assert.ok(fs.existsSync(path.join(root, '.codex/hooks.json')));
      assert.ok(fs.existsSync(path.join(root, '.code-flow/templates/task.md')));
    }
  }
});

test('project launcher resolves the bridge and preserves prompt context', { skip: process.platform === 'win32' }, async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const file = h.task(root);
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8')).hooks;
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  const result = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: JSON.stringify({ cwd: root, session_id: 'launcher', prompt: 'task: ' + file + '#TASK-001' }) });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(JSON.parse(result.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/launcher/bridge.cjs')));
  fs.rmSync(path.join(root, '.code-flow/launcher/hook.sh'));
  const missing = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: JSON.stringify({ cwd: root, session_id: 'missing', prompt: 'continue' }) });
  assert.equal(missing.status, 0);
  assert.equal(missing.stdout, '');
});

function fakeGlobal(base, options = {}) {
  const protocol = options.protocol ?? 1, context = options.context ?? 'PATH CONTEXT';
  const mode = options.mode ?? 'normal';
  const delay = mode === 'slow-capabilities' ? 900 : 0;
  const pkgDir = path.join(base, 'node_modules/@michaelxwb/code-flow');
  const binDir = path.join(base, 'bin');
  const entry = path.join(pkgDir, 'bin/code-flow.js');
  fs.mkdirSync(binDir, { recursive: true });
  fs.mkdirSync(path.dirname(entry), { recursive: true });
  fs.writeFileSync(path.join(pkgDir, 'package.json'), JSON.stringify({
    name: '@michaelxwb/code-flow', version: '9.9.9', bin: { 'code-flow': 'bin/code-flow.js' },
    codeFlow: { hookProtocol: protocol }
  }));
  const capability = (options.marker ? "require('fs').appendFileSync(" +
    JSON.stringify(options.marker) + ",'x');" : '') +
    "console.log(JSON.stringify({package:'@michaelxwb/code-flow',version:'9.9.9'," +
    "hook_protocol:" + protocol + ",node:process.execPath,entry:__filename}));process.exit(0)";
  const lines = [
    "const args=process.argv.slice(2);",
    "if(args[0]==='hook'&&args[1]==='capabilities'){",
    delay ? "setTimeout(()=>{" + capability + "}," + delay + ");}" : capability + "}"
  ];
  if (mode === 'corrupt') lines.push("console.log('not-json');process.exit(0)");
  else if (mode === 'invalid-payload') lines.push("console.log('null');process.exit(0)");
  else if (mode === 'extra-fields') lines.push("let raw='';process.stdin.on('data',c=>raw+=c);",
    "process.stdin.on('end',()=>console.log(JSON.stringify({hookSpecificOutput:{",
    "hookEventName:'UserPromptSubmit',additionalContext:'PATH CONTEXT'},decision:'block',reason:'x'})))");
  else if (mode === 'huge') lines.push("process.stdout.write('x'.repeat(2*1024*1024));process.exit(0)");
  else if (mode === 'stderr-failure') lines.push("process.stderr.write('x'.repeat(2*1024*1024)+" +
    "'\\nLATEST DIAGNOSTIC\\n',()=>process.exit(1))");
  else if (mode === 'utf8-chunks') lines.push(
    "const bytes=Buffer.from(JSON.stringify({hookSpecificOutput:{hookEventName:'UserPromptSubmit'," +
    "additionalContext:" + JSON.stringify(context) + "}}));",
    "const cut=bytes.indexOf(Buffer.from('规则'))+1;process.stdout.write(bytes.subarray(0,cut));",
    "setTimeout(()=>process.stdout.write(bytes.subarray(cut)),30)");
  else if (mode === 'hang') lines.push("setInterval(()=>{},1000)");
  else lines.push("let raw='';process.stdin.on('data',c=>raw+=c);",
    "process.stdin.on('end',()=>console.log(JSON.stringify({hookSpecificOutput:{",
    "hookEventName:'UserPromptSubmit',additionalContext:" + JSON.stringify(context) + "}})))");
  fs.writeFileSync(entry, lines.join('\n'));
  const shim = path.join(binDir, 'code-flow');
  fs.writeFileSync(shim, '#!/bin/sh\nexec "' + process.execPath + '" "' + entry + '" "$@"\n');
  fs.chmodSync(shim, 0o755);
  return { bin: binDir, entry };
}

test('launcher preserves UTF-8 context split across child output chunks', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  const context = '规则：保持用户内容。'.repeat(8000);
  const fake = fakeGlobal(empty(t), { mode: 'utf8-chunks', context });
  const result = spawnSync(process.execPath, [path.join(root, '.code-flow/launcher/bridge.cjs'),
    '--format', 'codex', '--node', process.execPath, '--entry', fake.entry], {
    cwd: root, env: { ...process.env, PATH: '' }, input: '{"prompt":"continue"}',
    encoding: 'utf8', maxBuffer: 1024 * 1024
  });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(JSON.parse(result.stdout).hookSpecificOutput.additionalContext === context,
    'UTF-8 context must match the complete original text');
});

test('launcher bounds accumulated child diagnostics and retains the latest error', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  const fake = fakeGlobal(empty(t), { mode: 'stderr-failure' });
  const result = spawnSync(process.execPath, [path.join(root, '.code-flow/launcher/bridge.cjs'),
    '--format', 'codex', '--node', process.execPath, '--entry', fake.entry], {
    cwd: root, env: { ...process.env, PATH: '' }, input: '{"prompt":"continue"}',
    encoding: 'utf8', maxBuffer: 4 * 1024 * 1024
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).hookSpecificOutput.additionalContext, '');
  assert.ok(Buffer.byteLength(result.stderr) <= 8192, 'diagnostics must stay bounded');
  assert.ok(result.stderr.endsWith('LATEST DIAGNOSTIC\n'));
});

test('launcher prefers a validated PATH package and falls back when it is invalid', { skip: process.platform === 'win32' }, async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const file = h.task(root);
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8')).hooks;
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  const prompt = JSON.stringify({ cwd: root, session_id: 'path', prompt: 'task: ' + file + '#TASK-001' });
  const fakeBase = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-global-'));
  const brokenBase = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-global-broken-'));
  const corruptBase = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-global-corrupt-'));
  t.after(() => { for (const directory of [fakeBase, brokenBase, corruptBase])
    fs.rmSync(directory, { recursive: true, force: true }); });
  const fake = fakeGlobal(fakeBase);
  spawnSync(path.join(fake.bin, 'code-flow'), ['hook', 'capabilities', '--json'], { encoding: 'utf8' });
  const preferred = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: fake.bin + path.delimiter + process.env.PATH } });
  assert.equal(preferred.status, 0, preferred.stderr);
  assert.equal(JSON.parse(preferred.stdout).hookSpecificOutput.additionalContext, 'PATH CONTEXT');
  const broken = fakeGlobal(brokenBase, { protocol: 2 });
  spawnSync(path.join(broken.bin, 'code-flow'), ['hook', 'capabilities', '--json'], { encoding: 'utf8' });
  const fallback = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: broken.bin + path.delimiter + process.env.PATH } });
  assert.equal(fallback.status, 0, fallback.stderr);
  assert.ok(JSON.parse(fallback.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  const corrupt = fakeGlobal(corruptBase, { context: '', mode: 'corrupt' });
  spawnSync(path.join(corrupt.bin, 'code-flow'), ['hook', 'capabilities', '--json'], { encoding: 'utf8' });
  const discarded = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: corrupt.bin + path.delimiter + process.env.PATH } });
  assert.equal(discarded.status, 0, discarded.stderr);
  assert.equal(JSON.parse(discarded.stdout).hookSpecificOutput.additionalContext, '');
  const invalid = fakeGlobal(corruptBase, { mode: 'invalid-payload' });
  spawnSync(path.join(invalid.bin, 'code-flow'), ['hook', 'capabilities', '--json'], { encoding: 'utf8' });
  const malformed = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: invalid.bin + path.delimiter + process.env.PATH } });
  assert.equal(malformed.status, 0, malformed.stderr);
  assert.equal(JSON.parse(malformed.stdout).hookSpecificOutput.additionalContext, '');
  const extra = fakeGlobal(corruptBase, { mode: 'extra-fields' });
  spawnSync(path.join(extra.bin, 'code-flow'), ['hook', 'capabilities', '--json'], { encoding: 'utf8' });
  const filtered = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: extra.bin + path.delimiter + process.env.PATH } });
  const payload = JSON.parse(filtered.stdout);
  assert.equal(filtered.status, 0, filtered.stderr);
  assert.equal(payload.hookSpecificOutput.additionalContext, 'PATH CONTEXT');
  assert.equal(Object.hasOwn(payload, 'decision'), false);
  assert.equal(Object.hasOwn(payload, 'reason'), false);
  const local = path.join(root, 'node_modules/.bin');
  fs.mkdirSync(local, { recursive: true });
  fs.copyFileSync(path.join(fake.bin, 'code-flow'), path.join(local, 'code-flow'));
  fs.chmodSync(path.join(local, 'code-flow'), 0o755);
  const rejected = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: local + path.delimiter + process.env.PATH } });
  assert.equal(rejected.status, 0, rejected.stderr);
  assert.ok(JSON.parse(rejected.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
});

test('launcher bounds child output/time and ignores slow PATH probes', { skip: process.platform === 'win32' }, async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const file = h.task(root);
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8')).hooks;
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  const prompt = JSON.stringify({ cwd: root, session_id: 'bounds', prompt: 'task: ' + file + '#TASK-001' });
  const bases = {};
  const fakes = {};
  for (const mode of ['huge', 'hang', 'slow-capabilities']) {
    bases[mode] = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-global-' + mode + '-'));
  }
  t.after(() => { for (const base of Object.values(bases)) fs.rmSync(base, { recursive: true, force: true }); });
  for (const mode of ['huge', 'hang', 'slow-capabilities']) {
    fakes[mode] = fakeGlobal(bases[mode], { mode });
    spawnSync(path.join(fakes[mode].bin, 'code-flow'), ['hook', 'capabilities', '--json'],
      { encoding: 'utf8', timeout: 1500 });
  }
  for (const mode of ['huge', 'hang']) {
    const fake = fakes[mode];
    const started = Date.now();
    const result = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
      input: prompt, env: { ...process.env, PATH: fake.bin + path.delimiter + process.env.PATH } });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).hookSpecificOutput.additionalContext, '');
    if (mode === 'hang') assert.ok(Date.now() - started < 5000, 'bridge must bound total time');
  }
  const slow = fakes['slow-capabilities'];
  const fallback = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: slow.bin + path.delimiter + process.env.PATH } });
  assert.equal(fallback.status, 0, fallback.stderr);
  assert.ok(JSON.parse(fallback.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
});

test('launcher reserves execution time when many PATH probes are slow', { skip: process.platform === 'win32' }, async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const file = h.task(root);
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8')).hooks;
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  const prompt = JSON.stringify({ cwd: root, session_id: 'reserve', prompt: 'task: ' + file + '#TASK-001' });
  const bins = [];
  for (let index = 0; index < 9; index++) {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-slow-probe-' + index + '-'));
    t.after(() => fs.rmSync(base, { recursive: true, force: true }));
    bins.push(fakeGlobal(base, { mode: 'slow-capabilities' }).bin);
  }
  const started = Date.now();
  const result = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8',
    input: prompt, env: { ...process.env, PATH: bins.join(path.delimiter) + path.delimiter + process.env.PATH } });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(JSON.parse(result.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'),
    'the fixed entry must still get execution budget');
  assert.ok(Date.now() - started < 5000);
});

test('launcher caches a validated PATH package and re-probes after expiry', { skip: process.platform === 'win32' }, async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); const file = h.task(root);
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8')).hooks;
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  const prompt = JSON.stringify({ cwd: root, session_id: 'cache', prompt: 'task: ' + file + '#TASK-001' });
  const marker = path.join(os.tmpdir(), 'cf-probe-' + process.pid + '-' + Date.now() + '.log');
  t.after(() => fs.rmSync(marker, { force: true }));
  const fake = fakeGlobal(empty(t), { marker, context: 'CACHED CONTEXT' });
  const env = { ...process.env, PATH: fake.bin + path.delimiter + process.env.PATH };
  const first = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8', input: prompt, env });
  assert.equal(first.status, 0, first.stderr);
  assert.equal(JSON.parse(first.stdout).hookSpecificOutput.additionalContext, 'CACHED CONTEXT');
  assert.equal(fs.readFileSync(marker, 'utf8'), 'x');
  const second = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8', input: prompt, env });
  assert.equal(JSON.parse(second.stdout).hookSpecificOutput.additionalContext, 'CACHED CONTEXT');
  assert.equal(fs.readFileSync(marker, 'utf8'), 'x', 'cache hit must not probe again');
  const digest = crypto.createHash('sha256').update(fs.realpathSync(root)).digest('hex');
  const cache = path.join(os.tmpdir(), 'code-flow', digest, 'bridge.json');
  const data = JSON.parse(fs.readFileSync(cache, 'utf8'));
  data.checked_at = 0;
  fs.writeFileSync(cache, JSON.stringify(data));
  const third = spawnSync('/bin/sh', ['-c', command], { cwd: root, encoding: 'utf8', input: prompt, env });
  assert.equal(JSON.parse(third.stdout).hookSpecificOutput.additionalContext, 'CACHED CONTEXT');
  assert.equal(fs.readFileSync(marker, 'utf8'), 'xx', 'expired cache must probe again');
});

test('launcher bridge exits when stdin stalls past its deadline', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  const bridge = path.join(root, '.code-flow/launcher/bridge.cjs');
  const child = spawn(process.execPath, [bridge, '--format', 'codex', '--node', process.execPath,
    '--entry', path.resolve(__dirname, '../bin/code-flow.js')],
  { cwd: root, stdio: ['pipe', 'ignore', 'ignore'] });
  t.after(() => { if (child.exitCode === null) child.kill('SIGKILL'); });
  child.stdin.write('{');
  const code = await new Promise(resolve => {
    const timer = setTimeout(() => resolve('timeout'), 4000);
    child.once('close', value => { clearTimeout(timer); resolve(value); });
  });
  assert.equal(code, 0);
});

test('init --platform=all installs all four user command layouts', async t => {
  const root = empty(t);
  const result = await init.init(root, { platform: 'all' });
  assert.deepEqual(result.platforms, ['claude', 'codex', 'costrict', 'opencode']);
  for (const relative of ['.claude/commands/cf-task/prd.md', '.costrict/commands/cf-task/plan.md',
    '.opencode/commands/cf-task/start.md', '.agents/skills/cf-task-archive/SKILL.md']) {
    assert.ok(fs.existsSync(path.join(root, relative)), relative);
  }
  for (const relative of ['.claude/commands/cf-task/finish.md', '.claude/commands/cf-task/status.md',
    '.claude/commands/cf-task/block.md', '.claude/commands/cf-task/reopen.md',
    '.agents/skills/cf-task-finish/SKILL.md', '.agents/skills/cf-task-parallel/SKILL.md']) {
    assert.equal(fs.existsSync(path.join(root, relative)), false, relative);
  }
  const names = fs.readdirSync(path.join(root, '.code-flow/templates')).sort();
  assert.deepEqual(names, ['design-frontend.md', 'design-full.md', 'design-lite.md',
    'prd.md', 'project-guidelines.md', 'scenarios.md', 'task.md']);
});

test('all installed v1 platforms update together and user config/hooks survive', async t => {
  const root = empty(t);
  h.write(root, '.codex/config.toml', 'model="user-choice"\n[features]\nhooks = false # user comment\nother = true\n');
  h.write(root, '.codex/hooks.json', JSON.stringify({ userSetting: true, hooks: {
    Stop: [{ hooks: [{ type: 'command', command: 'echo user-custom' }] }]
  } }));
  h.write(root, 'AGENTS.md', 'User instruction must stay.\n');
  for (const platform of ['codex', 'claude', 'costrict', 'opencode']) await init.init(root, { platform });
  const update = await init.init(root, { node: '/new/node', entry: '/new/bin/code-flow.js' });
  assert.equal(update.platforms.length, 4, update.platforms.join(','));
  assert.ok(fs.existsSync(path.join(root, '.claude/commands/cf-task/prd.md')));
  assert.ok(fs.existsSync(path.join(root, '.agents/skills/cf-task-prd/SKILL.md')));
  assert.ok(fs.existsSync(path.join(root, '.opencode/commands/cf-task/start.md')));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/templates/prd.md')));
  const hooks = JSON.parse(fs.readFileSync(path.join(root, '.codex/hooks.json'), 'utf8'));
  assert.equal(hooks.userSetting, true); assert.equal(hooks.hooks.Stop[0].hooks[0].command, 'echo user-custom');
  const launcher = process.platform === 'win32' ? 'hook.ps1' : 'hook.sh';
  assert.ok(hooks.hooks.UserPromptSubmit[0].hooks[0].command.includes(launcher));
  assert.ok(fs.readFileSync(path.join(root, '.code-flow/launcher/hook.sh'), 'utf8').includes('/new/node'));
  assert.ok(fs.readFileSync(path.join(root, 'AGENTS.md'), 'utf8').startsWith('User instruction'));
  const toml = fs.readFileSync(path.join(root, '.codex/config.toml'), 'utf8');
  assert.ok(toml.includes('model="user-choice"') && toml.includes('hooks = true # user comment'));
});
test('unknown nonempty data and unmanaged skill/plugin files are preserved', async t => {
  const root = empty(t); h.write(root, '.code-flow/user.txt', 'precious');
  await assert.rejects(init.init(root, { platform: 'codex' }), /Nonempty/);
  assert.equal(fs.readFileSync(path.join(root, '.code-flow/user.txt'), 'utf8'), 'precious');
  const other = empty(t); h.write(other, '.agents/skills/cf-init/SKILL.md', 'custom skill');
  const conflicted = await init.init(other, { platform: 'codex' });
  assert.equal(conflicted.ok, false);
  assert.ok(conflicted.conflicts.some(item => item.path === '.agents/skills/cf-init/SKILL.md'));
  assert.equal(fs.readFileSync(path.join(other, '.agents/skills/cf-init/SKILL.md'), 'utf8'), 'custom skill');
  assert.ok(fs.existsSync(path.join(other, '.code-flow/templates/task.md')));
  assert.ok(fs.existsSync(path.join(other, '.codex/hooks.json')));
  fs.rmSync(path.join(other, '.agents/skills/cf-init/SKILL.md'));
  const resolved = await init.init(other, { platform: 'codex' });
  assert.equal(resolved.ok, true);
  assert.equal(resolved.conflicts.length, 0);
  assert.ok(fs.readFileSync(path.join(other, '.agents/skills/cf-init/SKILL.md'), 'utf8').includes('cf-init'));
});

test('init reports per-file conflicts and still installs other files', async t => {
  const root = empty(t);
  const file = h.write(root, '.codex/config.toml', '[features]\n"hooks" = false\n');
  const result = await init.init(root, { platform: 'codex' });
  assert.equal(result.ok, false);
  assert.ok(result.conflicts.some(item => item.path === '.codex/config.toml' && item.code === 'config_format'));
  assert.equal(fs.readFileSync(file, 'utf8'), '[features]\n"hooks" = false\n');
  assert.ok(fs.existsSync(path.join(root, '.codex/hooks.json')));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/templates/task.md')));
  assert.ok(fs.existsSync(path.join(root, '.agents/skills/cf-init/SKILL.md')));
});
test('POSIX launcher quotes hostile-looking paths, handles missing entry and preserves stdin JSON', async t => {
  if (process.platform === 'win32') return;
  const root = empty(t), entry = h.write(root, "a ' $ (quoted)/entry.js", 'process.stdout.write(JSON.stringify({native:JSON.parse(require("fs").readFileSync(0,"utf8"))}));');
  const command = adapters.posix(process.execPath, entry, 'codex');
  const result = spawnSync('/bin/sh', ['-c', command], { input: '{"prompt":"ok"}', encoding: 'utf8' });
  assert.equal(result.status, 0); assert.equal(JSON.parse(result.stdout).native.prompt, 'ok');
  const missing = spawnSync('/bin/sh', ['-c', adapters.posix(process.execPath, entry + '.missing', 'codex')], { encoding: 'utf8' });
  assert.equal(missing.status, 0); assert.equal(missing.stdout, ''); assert.ok(missing.stderr.includes('missing'));
});
test('OpenCode native prompt/context delivers to correct session without rejection on failures', async t => {
  const root = empty(t); await init.init(root, { platform: 'opencode' }); h.spec(root); const file = h.task(root);
  const pluginFile = path.join(root, '.opencode/plugins/code-flow/index.js');
  const plugin = (await import(pathToFileURL(pluginFile).href)).default;
  const hooks = {};
  let fail = false;
  const cleanup = await plugin.setup({ session: {
    hook: async (name, fn) => { hooks[name] = fn; },
    get: async ({ sessionID }) => {
      if (sessionID === 'broken' || fail) throw new Error('lookup failed');
      return { location: { directory: root } };
    }
  } });
  t.after(cleanup);
  await hooks.prompt({ sessionID: 'one', prompt: { text: 'task: ' + file + '#TASK-001' } });
  const other = { sessionID: 'other', system: [] }; await hooks.context(other); assert.equal(other.system.length, 0);
  const own = { sessionID: 'one', system: [] }; await hooks.context(own);
  assert.ok(own.system[0].text.includes('Current rule.'));
  const nextTurn = { sessionID: 'one', system: [] }; await hooks.context(nextTurn);
  assert.ok(nextTurn.system[0].text.includes('Current rule.'));
  const original = console.error, errors = []; console.error = text => errors.push(text);
  try { await hooks.prompt({ sessionID: 'broken', prompt: { text: 'continue' } }); }
  finally { console.error = original; }
  assert.ok(errors.some(text => text.includes('lookup failed')));
  fail = true; console.error = text => errors.push(text);
  try { await hooks.prompt({ sessionID: 'one', prompt: { text: 'continue' } }); }
  finally { console.error = original; }
  const afterFailure = { sessionID: 'one', system: [] }; await hooks.context(afterFailure);
  assert.equal(afterFailure.system.length, 0);
});
test('Windows adapters target the project launcher and preserve fail-open behavior', () => {
  assert.equal(adapters.owned('// code-flow:v1\r\nimport'), true);
  assert.equal(adapters.owned('// code-flow:v1\nimport'), true);
  const codex = adapters.hook('codex', 'C:\\Program Files\\node.exe', 'C:\\global\\bin\\code-flow.js', 'win32');
  assert.ok(codex.commandWindows.includes('hook.cmd'));
  assert.ok(codex.commandWindows.includes('if exist'));
  assert.ok(codex.commandWindows.includes('exit /b 0'));
  const claude = adapters.hook('claude', 'C:\\node.exe', 'C:\\global\\bin\\code-flow.js', 'win32');
  assert.equal(claude.shell, 'powershell'); assert.equal(claude.onFailure, 'continue');
  assert.ok(claude.command.includes('hook.ps1'));
  assert.ok(claude.command.includes('Test-Path'));
  assert.ok(claude.command.includes('exit 0'));
  const posix = adapters.hook('codex', '/usr/bin/node', '/global/bin/code-flow.js', 'linux');
  assert.ok(posix.command.includes('if [ -f'));
  assert.ok(posix.command.includes('hook.sh'));
  assert.ok(posix.command.includes('exit 0'));
});
