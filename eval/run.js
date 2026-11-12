'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const os = require('node:os');
const f = require('../lib/fs');

const ROOT = __dirname;
const REPO = path.resolve(ROOT, '..');
const FIXTURES = path.join(ROOT, 'fixtures');
const WRAPPER = path.join(ROOT, 'bin', 'code-flow');
const FAKE = path.join(ROOT, 'fake-agent.js');
const MODES = ['full', 'hook', 'minimal'];
const STAMP = new Date().toISOString().replace(/[:.]/g, '-');

function usage(message) {
  if (message) process.stderr.write(message + '\n');
  process.stderr.write('Usage: node eval/run.js (--all | --fixture <name>) [--path full|minimal] ' +
    '[--runs <n>] [--agent <command>] [--timeout <seconds>] [--keep] [--dry-run] [--out <dir>]\n' +
    '  --agent reads the prompt from $EVAL_PROMPT_FILE and runs in the workspace (cwd).\n' +
    '  Set AGENT_CMD instead of --agent. --dry-run uses the built-in fake agent.\n');
  process.exit(message ? 2 : 0);
}

function parseArgs(argv) {
  const options = { all: false, fixture: null, mode: null, runs: 1, agent: process.env.AGENT_CMD || null,
    timeout: 1200, keep: false, dryRun: false, out: null };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--all') options.all = true;
    else if (arg === '--fixture') options.fixture = argv[++index];
    else if (arg === '--path') options.mode = argv[++index];
    else if (arg === '--runs') options.runs = Number(argv[++index]);
    else if (arg === '--agent') options.agent = argv[++index];
    else if (arg === '--timeout') options.timeout = Number(argv[++index]);
    else if (arg === '--keep') options.keep = true;
    else if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '--out') options.out = argv[++index];
    else if (arg === '--help' || arg === '-h') usage();
    else usage('Unknown argument: ' + arg);
  }
  if (!options.all && !options.fixture) usage('Pass --all or --fixture <name>.');
  if (options.mode && !MODES.includes(options.mode)) usage('--path must be full or minimal.');
  if (!Number.isSafeInteger(options.runs) || options.runs < 1) usage('--runs must be a positive integer.');
  if (!Number.isFinite(options.timeout) || options.timeout <= 0) usage('--timeout must be positive.');
  if (options.dryRun && !options.agent) options.agent = JSON.stringify(process.execPath) + ' ' + JSON.stringify(FAKE);
  if (!options.agent) usage('Pass --agent or set AGENT_CMD.');
  return options;
}

function fixtureNames() {
  return fs.readdirSync(FIXTURES, { withFileTypes: true })
    .filter(entry => entry.isDirectory()).map(entry => entry.name).sort();
}

function write(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

function git(cwd, args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8' });
  if (result.status !== 0) throw new Error('git ' + args.join(' ') + ': ' + result.stderr.trim());
  return result.stdout.trim();
}

function promptFor(fixture, mode, workspace) {
  const task = fs.readFileSync(path.join(FIXTURES, fixture, 'workspace/TASK.md'), 'utf8');
  const metaFile = path.join(FIXTURES, fixture, 'fixture.json');
  const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
  const count = meta.tasks ?? 1;
  const ids = Array.from({ length: count }, (_, index) => 'TASK-' + String(index + 1).padStart(3, '0'));
  const taskList = ids.map((id, index) => index === 0 ? id : id + ' (Depends: ' + ids[index - 1] + ')').join(', ');
  const document = '.code-flow/tasks/2026-11-12/' + fixture + '/' + fixture + '.md';
  const common = 'You are working in ' + workspace + '.\n\n' + task +
    '\n\nImplement the requirement and add tests. Do not modify files outside the workspace.\n';
  if (mode === 'minimal') return common + '\nRun the tests before finishing.\n';
  if (mode === 'hook') return common + '\nUse code-flow task state only:\n' +
    '1. Create one task document ' + document + ' with sections: ' + taskList + '. ' +
    'Each section needs a ### Tests JSON array and Spec-Refs: shared/base.\n' +
    '2. Run code-flow task start/finish for each section in order.\n' +
    '3. Implement the code and tests.\n' +
    'Do not create PRD, design or scenario documents.\n';
  return common + '\nUse the code-flow v1 workflow:\n' +
    '1. Create requirement documents under .code-flow/tasks/2026-11-12/' + fixture + '/: ' +
    fixture + '.prd.md, ' + fixture + '.design.md, ' + fixture + '.scenarios.md.\n' +
    '2. Create one task document ' + document + ' with sections: ' + taskList + '. ' +
    'Each section needs a ### Tests JSON array and Spec-Refs: shared/base.\n' +
    '3. Run code-flow task start/finish for each section in order.\n' +
    '4. Implement the code and tests.\n' +
    'Keep the documents and tests.\n';
}

function toolchain() {
  if (process.env.EVAL_CODE_FLOW_ENTRY) return { entry: process.env.EVAL_CODE_FLOW_ENTRY, cleanup: () => {} };
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-eval-tool-'));
  const pack = spawnSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', root],
    { cwd: REPO, encoding: 'utf8' });
  if (pack.status !== 0) throw new Error('npm pack failed: ' + (pack.stderr || pack.stdout));
  const tarball = JSON.parse(pack.stdout)[0].filename;
  const prefix = path.join(root, 'prefix');
  const install = spawnSync('npm', ['install', '--global', '--prefix', prefix, '--ignore-scripts',
    '--no-audit', '--no-fund', path.join(root, tarball)], { encoding: 'utf8' });
  if (install.status !== 0) throw new Error('npm install failed: ' + (install.stderr || install.stdout));
  const modules = spawnSync('npm', ['root', '--global', '--prefix', prefix], { encoding: 'utf8' }).stdout.trim();
  const entry = path.join(modules, '@michaelxwb/code-flow/bin/code-flow.js');
  if (!fs.existsSync(entry)) throw new Error('installed entry missing: ' + entry);
  const binDir = path.join(root, 'bin');
  fs.mkdirSync(binDir, { recursive: true });
  fs.copyFileSync(WRAPPER, path.join(binDir, 'code-flow'));
  fs.chmodSync(path.join(binDir, 'code-flow'), 0o755);
  return { entry, binDir, cleanup: () => fs.rmSync(root, { recursive: true, force: true }) };
}

function prepare(fixture, mode, runId, outDir, workDir, tool) {
  const resultDir = path.join(outDir, runId);
  fs.mkdirSync(resultDir, { recursive: true });
  const workspace = path.join(workDir, runId);
  const repoPrefix = REPO + path.sep;
  if (path.resolve(workspace).startsWith(repoPrefix) || path.resolve(tool.entry).startsWith(repoPrefix)) {
    throw new Error('eval workspace and toolchain must be outside the repository');
  }
  fs.cpSync(path.join(FIXTURES, fixture, 'workspace'), workspace, { recursive: true });
  git(workspace, ['init', '-q']);
  git(workspace, ['config', 'user.name', 'Eval']);
  git(workspace, ['config', 'user.email', 'eval@example.invalid']);
  git(workspace, ['add', '-A']);
  git(workspace, ['commit', '-qm', 'baseline']);
  const promptFile = path.join(workDir, runId + '.prompt.md');
  const cliLog = path.join(workDir, runId + '.cli.jsonl');
  const env = { ...process.env, EVAL_WORKSPACE: workspace, EVAL_FIXTURE: fixture,
    EVAL_PATH: mode, EVAL_CODE_FLOW_ENTRY: tool.entry };
  delete env.OLDPWD;
  delete env.INIT_CWD;
  delete env.CLAUDE_PROJECT_DIR;
  env.PWD = workspace;
  if (mode !== 'minimal') {
    env.PATH = tool.binDir + path.delimiter + process.env.PATH;
    env.EVAL_CLI_LOG = cliLog;
    fs.writeFileSync(env.EVAL_CLI_LOG, '');
    const init = spawnSync(process.execPath, [WRAPPER, 'init', '--platform=claude', '--json'],
      { cwd: workspace, env, encoding: 'utf8' });
    if (init.status !== 0) throw new Error('init failed: ' + (init.stderr || init.stdout));
    const metaFile = path.join(FIXTURES, fixture, 'fixture.json');
    const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
    const spec = meta.spec ? fs.readFileSync(path.join(FIXTURES, fixture, meta.spec), 'utf8') :
      '---\n{"description":"project rules","next_rule":2}\n---\n## Rules\n\n' +
      '- [RULE-001] Follow TASK.md and keep the public interface.\n';
    write(path.join(workspace, '.code-flow/specs/shared/base.md'), spec);
    const configFile = path.join(workspace, '.code-flow/config.json');
    const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
    config.always = ['shared/base'];
    config.workflow = mode === 'full' ? 'full' : 'hook';
    config.capture = { enabled: true, path: '.code-flow/process' };
    write(configFile, JSON.stringify(config, null, 2) + '\n');
    fs.writeFileSync(env.EVAL_CLI_LOG, '');
  }
  const eventLog = path.join(workspace, '.code-flow/process/events.jsonl');
  write(promptFile, promptFor(fixture, mode, workspace));
  write(path.join(resultDir, 'prompt.md'), fs.readFileSync(promptFile, 'utf8'));
  env.EVAL_PROMPT_FILE = promptFile;
  return { workspace, resultDir, env, promptFile, cliLog, eventLog };
}

function extractMetrics(stdout) {
  const text = String(stdout || '').trim();
  if (!text) return {};
  const pick = data => ({ is_error: data.is_error ?? null,
    cost_usd: data.total_cost_usd ?? data.cost_usd ?? null,
    duration_ms: data.duration_ms ?? null, turns: data.num_turns ?? null,
    tokens: data.usage ?? null, session_id: data.session_id ?? null });
  try { return pick(JSON.parse(text)); } catch (_) { /* not a single JSON object */ }
  const objects = text.split('\n').filter(line => line.trim().startsWith('{')).map(line => {
    try { return JSON.parse(line); } catch (_) { return null; }
  }).filter(Boolean);
  const withUsage = objects.filter(item => item.usage || item.total_token_usage ||
    item.type === 'turn.completed' || item.type === 'result');
  return withUsage.length ? pick(withUsage.at(-1)) : {};
}

function runAgent(command, prepared, timeoutSeconds) {
  const started = performance.now();
  const result = spawnSync('sh', ['-c', command], { cwd: prepared.workspace, env: prepared.env,
    timeout: timeoutSeconds * 1000, maxBuffer: 64 * 1024 * 1024, encoding: 'utf8' });
  fs.writeFileSync(path.join(prepared.resultDir, 'agent.stdout'), result.stdout || '');
  fs.writeFileSync(path.join(prepared.resultDir, 'agent.stderr'), result.stderr || '');
  if (prepared.eventLog && fs.existsSync(prepared.eventLog)) {
    fs.copyFileSync(prepared.eventLog, path.join(prepared.resultDir, 'events.jsonl'));
  }
  return { exit_code: result.status, signal: result.signal,
    error: result.error?.message || null, duration_ms: Math.round(performance.now() - started),
    stdout_bytes: Buffer.byteLength(result.stdout || ''), stderr_bytes: Buffer.byteLength(result.stderr || ''),
    metrics: extractMetrics(result.stdout || '') };
}

function verify(fixture, workspace) {
  const hidden = path.join(workspace, '.eval-hidden');
  fs.rmSync(hidden, { recursive: true, force: true });
  fs.mkdirSync(hidden, { recursive: true });
  fs.copyFileSync(path.join(FIXTURES, fixture, 'hidden/acceptance.test.js'),
    path.join(hidden, 'acceptance.test.js'));
  const result = spawnSync(process.execPath, ['--test', '.eval-hidden/acceptance.test.js'],
    { cwd: workspace, encoding: 'utf8', timeout: 60000 });
  fs.rmSync(hidden, { recursive: true, force: true });
  return { ok: result.status === 0, exit_code: result.status,
    output: ((result.stdout || '') + (result.stderr || '')).slice(-4000) };
}

function walk(directory, prefix = '') {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
    .flatMap(entry => {
      const relative = prefix + entry.name;
      return entry.isDirectory() ? walk(path.join(directory, entry.name), relative + '/') : [relative];
    });
}

function processMetrics(prepared) {
  const calls = [];
  if (fs.existsSync(prepared.cliLog)) {
    fs.copyFileSync(prepared.cliLog, path.join(prepared.resultDir, 'cli.jsonl'));
    for (const line of fs.readFileSync(prepared.cliLog, 'utf8').split('\n').filter(Boolean)) {
      try { calls.push(JSON.parse(line)); } catch (_) { /* ignore malformed log line */ }
    }
  }
  const status = spawnSync(process.execPath, [WRAPPER, 'task', 'status', '--json'],
    { cwd: prepared.workspace, env: prepared.env, encoding: 'utf8' });
  let items = [];
  try { items = JSON.parse(status.stdout).items || []; } catch (_) { /* no task document */ }
  const docs = walk(path.join(prepared.workspace, '.code-flow/tasks'))
    .filter(name => /\.(prd|design|scenarios)\.md$/.test(name));
  return { cli_calls: calls.length,
    finish_calls: calls.filter(call => call.args[0] === 'task' && call.args[1] === 'finish').length,
    injected_bytes: calls.reduce((sum, call) => sum + (call.stdoutBytes || 0), 0),
    tasks: items.length, done: items.length > 0 && items.every(item => item.status === 'done'),
    docs: docs.length };
}

function capture(prepared, tool) {
  if (prepared.env.EVAL_CLI_LOG === undefined) return null;
  const out = path.join(prepared.resultDir, 'capture');
  const result = spawnSync(path.join(tool.binDir, 'code-flow'),
    ['process', 'collect', '--out', out, '--json'], { cwd: prepared.workspace, encoding: 'utf8',
      env: { ...prepared.env, EVAL_CODE_FLOW_ENTRY: tool.entry,
        EVAL_CLI_LOG: path.join(out, 'collector-cli.jsonl') } });
  return { ok: result.status === 0, bundle: out,
    error: result.status === 0 ? null : (result.stderr || result.stdout).trim().slice(0, 400) };
}

function cleanup(prepared, keep) {
  const transient = f.transientRoot(prepared.workspace);
  if (!keep) fs.rmSync(prepared.workspace, { recursive: true, force: true });
  fs.rmSync(transient, { recursive: true, force: true });
}

function format(value) {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function summarize(results, outDir) {
  write(path.join(outDir, 'summary.json'), JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 2) + '\n');
  const lines = ['| fixture | path | run | verify | duration | cost | turns | cli | finish | done | docs |',
    '|---|---|---|---|---|---|---|---|---|---|---|'];
  for (const result of results) {
    lines.push('| ' + [result.fixture, result.path, result.run,
      result.verify ? (result.verify.ok ? 'PASS' : 'FAIL') : 'ERROR',
      format(result.agent?.duration_ms) + 'ms',
      format(result.agent?.metrics?.cost_usd), format(result.agent?.metrics?.turns),
      format(result.process?.cli_calls), format(result.process?.finish_calls),
      result.process ? (result.process.done ? 'yes' : 'no') : '-',
      format(result.process?.docs)].join(' | ') + ' |');
  }
  const passed = results.filter(result => result.verify?.ok).length;
  lines.push('', 'Verify passed: ' + passed + '/' + results.length + '. Results: ' + outDir);
  write(path.join(outDir, 'summary.md'), lines.join('\n') + '\n');
  process.stdout.write(lines.join('\n') + '\n');
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const fixtures = options.fixture ? [options.fixture] : fixtureNames();
  for (const fixture of fixtures) {
    if (!fixtureNames().includes(fixture)) usage('Unknown fixture: ' + fixture);
    if (!fs.existsSync(path.join(FIXTURES, fixture, 'hidden/acceptance.test.js'))) usage('Fixture has no hidden test: ' + fixture);
  }
  const modes = options.mode ? [options.mode] : MODES;
  const outDir = options.out ? path.resolve(options.out) : path.join(ROOT, 'results', STAMP);
  const workDir = path.join(os.tmpdir(), 'code-flow-eval', STAMP);
  const tool = toolchain();
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(workDir, { recursive: true });
  const results = [], cells = [];
  for (const fixture of fixtures) for (const mode of modes) for (let run = 1; run <= options.runs; run++) {
    cells.push({ fixture, mode, run });
  }
  for (let index = 0; index < cells.length; index++) {
    const { fixture, mode, run } = cells[index];
    const runId = fixture + '-' + mode + '-r' + run;
    process.stdout.write('[' + (index + 1) + '/' + cells.length + '] ' + runId + ' ... ');
    const result = { fixture, path: mode, run, run_id: runId, started_at: new Date().toISOString() };
    let prepared = null;
    try {
      prepared = prepare(fixture, mode, runId, outDir, workDir, tool);
      result.agent = runAgent(options.agent, prepared, options.timeout);
      result.verify = verify(fixture, prepared.workspace);
      result.process = mode !== 'minimal' ? processMetrics(prepared) : null;
      result.capture = mode !== 'minimal' ? capture(prepared, tool) : null;
    } catch (error) {
      result.error = error.message;
    } finally {
      if (prepared) cleanup(prepared, options.keep);
    }
    write(path.join(outDir, runId + '.json'), JSON.stringify(result, null, 2) + '\n');
    results.push(result);
    process.stdout.write(result.verify ? (result.verify.ok ? 'PASS' : 'FAIL') : 'ERROR');
    process.stdout.write('\n');
  }
  summarize(results, outDir);
  if (!options.keep) {
    fs.rmSync(workDir, { recursive: true, force: true });
    tool.cleanup();
  }
}

main();
