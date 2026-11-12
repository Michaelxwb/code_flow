'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = __dirname;
const REPO = path.resolve(ROOT, '..');
const FIXTURE = path.join(ROOT, 'fixtures/flywheel');
const WRAPPER = path.join(ROOT, 'bin/code-flow');
const STAMP = new Date().toISOString().replace(/[:.]/g, '-');
const BATCH_RULE = `Company ledger contract: retryAll must return { results, ledger }. results[i] is the value on success and undefined on failure. ledger[i] is { seq, ref, outcome }; seq is the 1-based position; ref is the operation's id string (or null); outcome is 'PASS' on success and 'FAIL_RETRY_EXHAUSTED' on failure. ledger includes every operation in input order, even after a failure. It must not stop on the first failure.`;
const GENERIC_SPEC = '---\n{"description":"project rules","next_rule":2}\n---\n## Rules\n\n' +
  '- [RULE-001] Follow the phase brief and keep the public interface.\n';

function usage(message) {
  if (message) process.stderr.write(message + '\n');
  process.stderr.write('Usage: node eval/flywheel.js [--dry-run] [--agent <command>] ' +
    '[--timeout <seconds>] [--keep] [--out <dir>]\n');
  process.exit(message ? 2 : 0);
}

function parseArgs(argv) {
  const options = { dryRun: false, agent: process.env.AGENT_CMD || null, timeout: 1200,
    keep: false, out: null };
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === '--dry-run') options.dryRun = true;
    else if (argv[index] === '--agent') options.agent = argv[++index];
    else if (argv[index] === '--timeout') options.timeout = Number(argv[++index]);
    else if (argv[index] === '--keep') options.keep = true;
    else if (argv[index] === '--out') options.out = argv[++index];
    else usage('Unknown argument: ' + argv[index]);
  }
  if (!options.dryRun && !options.agent) usage('Pass --agent or set AGENT_CMD.');
  if (!Number.isFinite(options.timeout) || options.timeout <= 0) usage('--timeout must be positive.');
  return options;
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

function toolchain() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-flywheel-tool-'));
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
  const binDir = path.join(root, 'bin');
  fs.mkdirSync(binDir, { recursive: true });
  fs.copyFileSync(WRAPPER, path.join(binDir, 'code-flow'));
  fs.chmodSync(path.join(binDir, 'code-flow'), 0o755);
  return { entry, binDir, cleanup: () => fs.rmSync(root, { recursive: true, force: true }) };
}

function envFor(workspace, tool, name) {
  const parent = path.dirname(workspace);
  const env = { ...process.env, EVAL_CODE_FLOW_ENTRY: tool.entry,
    PATH: tool.binDir + path.delimiter + process.env.PATH, PWD: workspace };
  delete env.OLDPWD; delete env.INIT_CWD; delete env.CLAUDE_PROJECT_DIR;
  env.EVAL_CLI_LOG = path.join(parent, name + '.cli.jsonl');
  return env;
}

function cli(args, workspace, env) {
  return spawnSync('code-flow', args, { cwd: workspace, env, encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024 });
}

function createProject(root, tool) {
  const workspace = path.join(root, 'project');
  fs.cpSync(path.join(FIXTURE, 'workspace'), workspace, { recursive: true });
  git(workspace, ['init', '-q']);
  git(workspace, ['config', 'user.name', 'Eval']);
  git(workspace, ['config', 'user.email', 'eval@example.invalid']);
  git(workspace, ['add', '-A']);
  git(workspace, ['commit', '-qm', 'baseline']);
  const env = envFor(workspace, tool, 'main');
  const init = cli(['init', '--platform=claude', '--json'], workspace, env);
  if (init.status !== 0) throw new Error('init failed: ' + (init.stderr || init.stdout));
  write(path.join(workspace, '.code-flow/specs/shared/base.md'), GENERIC_SPEC);
  const configFile = path.join(workspace, '.code-flow/config.json');
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  config.always = ['shared/base'];
  config.workflow = 'hook';
  config.capture = { enabled: true, path: '.code-flow/process' };
  write(configFile, JSON.stringify(config, null, 2) + '\n');
  return { workspace, env };
}

function promptFile(root, name, workspace, text) {
  const file = path.join(root, name + '.prompt.md');
  write(file, text);
  return file;
}

function promptA(workspace) {
  return 'You are working in ' + workspace + '.\n\n' +
    fs.readFileSync(path.join(FIXTURE, 'phase-a.md'), 'utf8') +
    '\n\nUse code-flow task state:\n' +
    '1. Create one task document .code-flow/tasks/2026-11-12/retry/retry.md with a ## TASK-001 section, ' +
    'a ### Tests JSON array and Spec-Refs: shared/base.\n' +
    '2. Implement src/retry.js and tests.\n' +
    '3. Record the company compliance ledger contract in the task document\'s ### Spec Delta JSON array as one add Delta ' +
    'targeting shared/base, with the exact rule from phase-a.md and evidence ' +
    '"company ledger contract decided in phase A".\n' +
    '4. Run code-flow task start/finish for TASK-001.\n';
}

function promptB(workspace) {
  return 'You are working in ' + workspace + '.\n\n' +
    fs.readFileSync(path.join(FIXTURE, 'phase-b.md'), 'utf8') +
    '\n\nThe project specs are the source of truth. Use code-flow task state:\n' +
    '1. Create one task document .code-flow/tasks/2026-11-12/batch/batch.md with a ## TASK-001 section, ' +
    'a ### Tests JSON array and Spec-Refs: shared/base.\n' +
    '2. Implement src/batch.js and tests.\n' +
    '3. Run code-flow task start/finish for TASK-001.\n';
}

function runAgent(command, workspace, env, timeoutSeconds) {
  const result = spawnSync('sh', ['-c', command], { cwd: workspace, env,
    timeout: timeoutSeconds * 1000, maxBuffer: 64 * 1024 * 1024, encoding: 'utf8' });
  return { exit_code: result.status, error: result.error?.message || null,
    stdout: result.stdout || '', stderr: result.stderr || '' };
}

function extractMetrics(stdout) {
  try {
    const data = JSON.parse(String(stdout || '').trim());
    return { cost_usd: data.total_cost_usd ?? null, turns: data.num_turns ?? null,
      duration_ms: data.duration_ms ?? null, is_error: data.is_error ?? null };
  } catch (_) { return {}; }
}

function writeTask(workspace, relative, requirement, tests, delta) {
  const body = `---\n{"version":1,"requirement":"${requirement}"}\n---\n# Tasks: ${requirement}\n\n` +
    `## TASK-001: Implement\n\n- **Status**: draft\n- **Spec-Refs**: shared/base\n\n` +
    `### Tests\n\n\`\`\`json\n${JSON.stringify(tests, null, 2)}\n\`\`\`\n\n` +
    `### Spec Delta\n\n\`\`\`json\n${JSON.stringify(delta, null, 2)}\n\`\`\`\n`;
  write(path.join(workspace, relative), body);
  return relative;
}

function runTask(workspace, env, relative) {
  for (const action of ['start', 'finish']) {
    const result = cli(['task', action, relative, '--task', 'TASK-001', '--json'], workspace, env);
    if (result.status !== 0) throw new Error('task ' + action + ' failed: ' + (result.stderr || result.stdout));
  }
}

function fakeA(workspace, env) {
  fs.cpSync(path.join(FIXTURE, 'solution-a'), workspace, { recursive: true, force: true });
  const relative = writeTask(workspace, '.code-flow/tasks/2026-11-12/retry/retry.md', 'retry',
    [{ id: 'visible', argv: ['node', '--test', 'test/retry.test.js'] }],
    [{ id: 'DELTA-001', op: 'add', target: 'shared/base', rule: BATCH_RULE,
      evidence: 'company ledger contract decided in phase A' }]);
  runTask(workspace, env, relative);
}

function fakeB(workspace, env, solution) {
  fs.cpSync(path.join(FIXTURE, solution), workspace, { recursive: true, force: true });
  const relative = writeTask(workspace, '.code-flow/tasks/2026-11-12/batch/batch.md', 'batch',
    [{ id: 'visible', argv: ['node', '--test', 'test/batch.test.js'] }], []);
  runTask(workspace, env, relative);
}

function findTask(workspace, env, marker) {
  const result = cli(['task', 'status', '--json'], workspace, env);
  if (result.status !== 0) return null;
  const items = JSON.parse(result.stdout).items || [];
  return items.find(item => item.task_file.includes(marker)) || items.at(-1) || null;
}

function learn(workspace, env, task) {
  const result = cli(['spec', 'learn', '--from-task', task.task_file, '--task', 'TASK-001', '--json'],
    workspace, env);
  let data = null;
  try { data = JSON.parse(result.stdout); } catch (_) { /* keep null */ }
  const spec = fs.readFileSync(path.join(workspace, '.code-flow/specs/shared/base.md'), 'utf8');
  return { ok: result.status === 0, error: result.status === 0 ? null :
    (result.stderr || result.stdout).trim().slice(0, 400), data,
    learned: spec.includes('FAIL_RETRY_EXHAUSTED') };
}

function verify(workspace) {
  const hidden = path.join(workspace, '.eval-hidden');
  fs.rmSync(hidden, { recursive: true, force: true });
  fs.mkdirSync(hidden, { recursive: true });
  fs.copyFileSync(path.join(FIXTURE, 'hidden/acceptance.test.js'), path.join(hidden, 'acceptance.test.js'));
  const result = spawnSync(process.execPath, ['--test', '.eval-hidden/acceptance.test.js'],
    { cwd: workspace, encoding: 'utf8', timeout: 60000 });
  fs.rmSync(hidden, { recursive: true, force: true });
  return { ok: result.status === 0, exit_code: result.status,
    output: ((result.stdout || '') + (result.stderr || '')).slice(-3000) };
}

function capture(workspace, out, tool, env) {
  const result = spawnSync(path.join(tool.binDir, 'code-flow'),
    ['process', 'collect', '--out', out, '--json'], { cwd: workspace, encoding: 'utf8',
      env: { ...env, EVAL_CODE_FLOW_ENTRY: tool.entry,
        EVAL_CLI_LOG: path.join(out, 'collector-cli.jsonl') } });
  return { ok: result.status === 0, bundle: out };
}

function bPhase(name, workspace, env, tool, options, outDir) {
  const prompt = promptFile(path.dirname(workspace), 'b-' + name, workspace, promptB(workspace));
  env.EVAL_PROMPT_FILE = prompt;
  let agent = null;
  if (options.dryRun) fakeB(workspace, env, name === 'control' ? 'solution-control' : 'solution-b');
  else {
    agent = runAgent(options.agent, workspace, env, options.timeout);
    write(path.join(outDir, name + '.agent.stdout'), agent.stdout);
    write(path.join(outDir, name + '.agent.stderr'), agent.stderr);
  }
  const task = findTask(workspace, env, '/batch/');
  const result = verify(workspace);
  const captured = capture(workspace, path.join(outDir, 'capture-' + name), tool, env);
  return { task, verify: result, agent: agent ? { exit_code: agent.exit_code, error: agent.error,
    metrics: extractMetrics(agent.stdout) } : null, capture: captured };
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const tool = toolchain();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-flywheel-run-'));
  const outDir = options.out ? path.resolve(options.out) : path.join(ROOT, 'results', 'flywheel-' + STAMP);
  fs.mkdirSync(outDir, { recursive: true });
  try {
    const { workspace, env } = createProject(root, tool);
    let a = null;
    if (options.dryRun) fakeA(workspace, env);
    else {
      const prompt = promptFile(root, 'a', workspace, promptA(workspace));
      env.EVAL_PROMPT_FILE = prompt;
      const agent = runAgent(options.agent, workspace, env, options.timeout);
      write(path.join(outDir, 'a.agent.stdout'), agent.stdout);
      write(path.join(outDir, 'a.agent.stderr'), agent.stderr);
      a = { exit_code: agent.exit_code, error: agent.error, metrics: extractMetrics(agent.stdout) };
    }
    const taskA = findTask(workspace, env, '/retry/');
    const control = path.join(root, 'control');
    fs.cpSync(workspace, control, { recursive: true });
    fs.rmSync(path.join(control, '.code-flow/tasks'), { recursive: true, force: true });
    fs.rmSync(path.join(control, '.code-flow/process'), { recursive: true, force: true });
    const controlEnv = envFor(control, tool, 'control');
    const learned = taskA ? learn(workspace, env, taskA) : { ok: false, learned: false, error: 'missing task A' };
    const mainB = bPhase('main', workspace, env, tool, options, outDir);
    const controlB = bPhase('control', control, controlEnv, tool, options, outDir);
    for (const [name, project] of [['main', workspace], ['control', control]]) {
      const log = path.join(project, '.code-flow/process/events.jsonl');
      if (fs.existsSync(log)) fs.copyFileSync(log, path.join(outDir, name + '.events.jsonl'));
    }
    const summary = { stamp: STAMP, dry_run: options.dryRun,
      a: { task: taskA, agent: a, learn: learned,
        spec_learned: learned.learned },
      b: { main: mainB, control: controlB },
      interpretation: mainB.verify.ok && !controlB.verify.ok ? 'flywheel-positive' :
        !mainB.verify.ok && !controlB.verify.ok ? 'both-failed' : 'no-difference' };
    write(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
    const lines = ['| phase | task done | verify | cost | turns | capture |',
      '|---|---|---|---|---|---|',
      '| A | ' + (taskA?.status === 'done' ? 'yes' : 'no') + ' | learn=' +
        (learned.ok ? 'ok' : 'failed') + ' learned=' + (learned.learned ? 'yes' : 'no') + ' | ' +
        (a?.metrics?.cost_usd ?? '-') + ' | ' + (a?.metrics?.turns ?? '-') + ' | - |',
      '| B main | ' + (mainB.task?.status === 'done' ? 'yes' : 'no') + ' | ' +
        (mainB.verify.ok ? 'PASS' : 'FAIL') + ' | ' + (mainB.agent?.metrics?.cost_usd ?? '-') + ' | ' +
        (mainB.agent?.metrics?.turns ?? '-') + ' | ' + (mainB.capture.ok ? 'yes' : 'no') + ' |',
      '| B control | ' + (controlB.task?.status === 'done' ? 'yes' : 'no') + ' | ' +
        (controlB.verify.ok ? 'PASS' : 'FAIL') + ' | ' + (controlB.agent?.metrics?.cost_usd ?? '-') + ' | ' +
        (controlB.agent?.metrics?.turns ?? '-') + ' | ' + (controlB.capture.ok ? 'yes' : 'no') + ' |',
      '', 'Interpretation: ' + summary.interpretation, 'Results: ' + outDir];
    write(path.join(outDir, 'summary.md'), lines.join('\n') + '\n');
    process.stdout.write(lines.join('\n') + '\n');
  } finally {
    if (!options.keep) { fs.rmSync(root, { recursive: true, force: true }); tool.cleanup(); }
  }
}

main();
