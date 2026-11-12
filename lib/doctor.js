'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const f = require('./fs');
const config = require('./config');
const spec = require('./spec');
const task = require('./task');
const taskdoc = require('./taskdoc');
const init = require('./init');
const runs = require('./runs');
const toml = require('./toml');

const TEMPLATES = init.WORKFLOW_TEMPLATES;
const LAUNCHER = init.launcherTemplates();

function check(code, severity, status, message, target = null, nextAction = '') {
  return { code, severity, status, path: target, message, next_action: nextAction };
}

function pass(code, message, target = null) {
  return check(code, 'info', 'pass', message, target, '');
}

function gitRead(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8',
    env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' } });
  return result.status === 0 ? result.stdout.trim() : null;
}

function configChecks(root) {
  try { return [{ value: config.load(root), checks: [pass('CONFIG_OK', 'config 可读取。', '.code-flow/config.json')] }]; }
  catch (error) {
    return [{ value: null, checks: [check('CONFIG_INVALID', 'error', 'fail', error.message,
      '.code-flow/config.json', '修复 config.json 后重试')] }];
  }
}

function templateChecks(root) {
  const directory = path.join(root, '.code-flow/templates');
  const checks = [];
  for (const name of TEMPLATES) {
    if (!fs.existsSync(path.join(directory, name))) {
      checks.push(check('TEMPLATE_MISSING', 'error', 'fail', '缺少工作流模板: ' + name,
        '.code-flow/templates/' + name, '运行 code-flow init'));
    }
  }
  const taskTemplate = f.readText(path.join(directory, 'task.md'));
  if (taskTemplate !== null && !/^## TASK-\d+:/m.test(taskTemplate)) {
    checks.push(check('TEMPLATE_INSTRUCTION_INVALID', 'error', 'fail',
      '任务模板缺少多 TASK 段格式。', '.code-flow/templates/task.md', '运行 code-flow init'));
  }
  return checks.length ? checks : [pass('TEMPLATE_OK', '工作流模板完整。', '.code-flow/templates')];
}

function fallbackFindings(root) {
  const text = f.readText(path.join(root, '.code-flow/launcher/hook.sh'));
  if (text === null) return [];
  const node = /--node '([^']+)'/.exec(text)?.[1];
  const entry = /--entry '([^']+)'/.exec(text)?.[1];
  if (!node || !entry || (fs.existsSync(node) && fs.existsSync(entry))) return [];
  return [check('HOOK_ENTRY_FALLBACK', 'warning', 'fail',
    '固定回退 Node/JS 入口不存在；PATH 全局包仍可能可用。', '.code-flow/launcher/hook.sh',
    '重新 code-flow init 或修复全局安装')];
}

function launcherChecks(root) {
  const checks = [];
  for (const name of LAUNCHER) {
    if (!fs.existsSync(path.join(root, '.code-flow/launcher', name))) {
      checks.push(check('HOOK_ENTRY_MISSING', 'error', 'fail', '项目启动器缺失: ' + name,
        '.code-flow/launcher/' + name, '运行 code-flow init'));
    }
  }
  checks.push(...fallbackFindings(root));
  let platforms = [];
  try { platforms = init.installed(root); } catch (error) {
    checks.push(check('HOOK_CONFIG_INVALID', 'error', 'fail', error.message,
      'platform configuration', '修复平台 Hook 配置'));
  }
  if (!platforms.length && !checks.some(item => item.code === 'HOOK_CONFIG_INVALID')) {
    checks.push(check('HOOK_CONFIG_INVALID', 'warning', 'fail', '未发现 v1 平台 Hook。',
      '.claude/.codex/.costrict/.opencode', '运行 code-flow init --platform=all'));
  }
  if (platforms.length) {
    const target = require('./adapters').PLATFORMS[platforms[0]].hooks;
    checks.push(check('HOST_TRUST_UNKNOWN', 'warning', 'unknown',
      '无法从文件确定宿主是否已加载并信任此 Hook。', target,
      '在宿主审阅 Hook，并提交一次 prompt 检查注入。'));
  }
  const errors = checks.filter(item => item.severity === 'error');
  const unhealthy = checks.some(item => item.code === 'HOOK_ENTRY_MISSING' ||
    item.code === 'HOOK_ENTRY_FALLBACK');
  if (!errors.length && !unhealthy) {
    checks.push(pass('HOOK_ENTRY_OK', '项目启动器与平台入口可静态读取。', '.code-flow/launcher'));
  }
  return checks;
}

function codexChecks(root) {
  const relative = '.codex/config.toml';
  const text = f.readText(path.join(root, relative));
  if (text === null) return [];
  const found = toml.featuresHooks(text);
  if (found.unsupported) return [check('CODEX_CONFIG_FORM', 'error', 'fail',
    'Codex config.toml 使用不支持的 features.hooks 形式: ' + found.unsupported,
    relative, '改成规范 [features] 表 + hooks = true，或根级单行 features.hooks = true')];
  if (found.header < 0 && found.key < 0) return [];
  if (found.value !== 'true') return [check('CODEX_HOOKS_DISABLED', 'warning', 'fail',
    'Codex config.toml 未启用 features.hooks。', relative,
    '在 [features] 表中加入 hooks = true，或运行 code-flow init')];
  return [pass('CODEX_CONFIG_OK', 'Codex config.toml 的 features.hooks 已启用。', relative)];
}

function specChecks(root, settings) {
  let listing;
  try { listing = spec.list(root); } catch (error) {
    return { ids: new Set(), checks: [check('SPEC_INVALID', 'error', 'fail', error.message,
      '.code-flow/specs', '修复 Spec 树')] };
  }
  const checks = listing.diagnostics.map(item => check('SPEC_INVALID', 'error', 'fail',
    item.message, item.source ? '.code-flow/specs/' + item.source + '.md' : '.code-flow/specs',
    '修复 Spec 文件'));
  const ids = new Set(listing.items.map(item => item.id));
  const refs = [];
  if (settings) {
    for (const value of settings.always) refs.push(config.reference(value));
    for (const values of Object.values(settings.paths)) {
      for (const value of values) refs.push(config.reference(value));
    }
  }
  for (const ref of refs) {
    if (!ids.has(ref.id)) checks.push(check('SPEC_REF_MISSING', 'error', 'fail',
      'config 引用了不存在的 Spec: ' + ref.id, '.code-flow/config.json', '修复引用或补充 Spec'));
  }
  if (!checks.length) checks.push(pass('SPEC_OK', 'Spec 格式与 config 引用有效。', '.code-flow/specs'));
  return { ids, checks };
}

function taskChecks(root, specIds) {
  let listing;
  try { listing = task.list(root); } catch (error) {
    return [check('TASK_INVALID', 'error', 'fail', error.message,
      '.code-flow/tasks', '修复任务文档')];
  }
  const checks = listing.diagnostics.map(item => check(
    item.code && item.code.startsWith('task_depends') ? 'TASK_DEPENDENCY_INVALID' : 'TASK_INVALID',
    'error', 'fail', item.message, item.source || '.code-flow/tasks', '修复任务文档'));
  for (const item of listing.items) {
    for (const ref of item.spec_refs) {
      if (!specIds.has(ref.split('#')[0])) checks.push(check('SPEC_REF_MISSING', 'error', 'fail',
        item.task + ' 引用了不存在的 Spec: ' + ref, item.task_file, '修复 Spec-Refs'));
    }
  }
  const files = [...new Set(listing.items.map(item => item.task_file))];
  for (const file of files) {
    try { taskdoc.batches(task.loadDocument(root, file).tasks); } catch (error) {
      checks.push(check('TASK_DEPENDENCY_INVALID', 'error', 'fail', error.message,
        file, '修复 Depends 或任务状态'));
    }
  }
  if (!checks.length) checks.push(pass('TASK_OK', '任务文档与依赖有效。', '.code-flow/tasks'));
  return checks;
}

function worktreeList(root) {
  const raw = gitRead(root, ['worktree', 'list', '--porcelain']);
  if (raw === null) return null;
  const entries = [];
  let current = null;
  for (const line of raw.split('\n')) {
    if (line.startsWith('worktree ')) { current = { path: line.slice(9), branch: null, head: null }; entries.push(current); }
    else if (current && line.startsWith('HEAD ')) current.head = line.slice(5);
    else if (current && line.startsWith('branch ')) current.branch = line.slice(7);
  }
  return entries;
}

function registeredWorker(registered, absolute) {
  return registered.find(item => {
    try { return f.realpath(item.path) === f.realpath(absolute); } catch (_) { return false; }
  });
}

function workerFindings(root, ledger, registered, record) {
  const checks = [];
  for (const worker of ledger.worktrees) {
    if (worker.status === 'removed') continue;
    const absolute = path.join(root, worker.path);
    if (!fs.existsSync(absolute) || !registeredWorker(registered, absolute)) {
      checks.push(check('WORKTREE_RECOVERY_REQUIRED', 'warning', 'fail',
        '缺少注册的 worker worktree: ' + worker.task, worker.path || record.file,
        '按 ledger 重建或显式放弃该 run'));
    } else if (worker.status === 'merged' && worker.collected_head &&
        gitRead(root, ['merge-base', '--is-ancestor', worker.collected_head, 'HEAD']) === null) {
      checks.push(check('WORKTREE_RECOVERY_REQUIRED', 'warning', 'fail',
        '已合并 worker 的提交不在协调历史中: ' + worker.task, worker.path,
        '检查分支重写并显式恢复 ledger'));
    }
  }
  return checks;
}

function runFindings(root, ledger, registered, record) {
  const checks = [];
  let rootMatches = false;
  try { rootMatches = f.realpath(ledger.coordinator.root) === f.realpath(root); } catch (_) { rootMatches = false; }
  if (!rootMatches) {
    checks.push(check('WORKTREE_IDENTITY_MISMATCH', 'error', 'fail',
      'ledger 协调工作区与当前项目不一致: ' + record.run_id, record.file,
      '在记录中的协调工作区运行 doctor'));
    return checks;
  }
  if (ledger.status !== 'done' && ledger.status !== 'aborted') {
    checks.push(check('WORKTREE_RECOVERY_REQUIRED', 'warning', 'fail',
      'worktree run 尚未完成: ' + record.status, record.file,
      '执行 code-flow task parallel status 后继续 merge/cleanup'));
  }
  if (!registered) return checks.concat(check('WORKTREE_RECOVERY_REQUIRED', 'warning', 'fail',
    'Git worktree 注册信息不可读取: ' + record.run_id, record.file, '检查 Git worktree 注册'));
  if (ledger.coordinator.branch && gitRead(root, ['symbolic-ref', '-q', 'HEAD']) !== ledger.coordinator.branch) {
    checks.push(check('WORKTREE_IDENTITY_MISMATCH', 'error', 'fail',
      '协调分支已切换: ' + record.run_id, record.file, '切回原分支或显式放弃 run'));
  }
  return checks.concat(workerFindings(root, ledger, registered, record));
}

function worktreeChecks(root) {
  let records;
  try { records = runs.list(root); } catch (error) {
    return [check('WORKTREE_LEDGER_INVALID', 'error', 'fail', error.message,
      '.code-flow/worktrees', '检查 worktree run 目录')];
  }
  if (!records.length) return [pass('WORKTREE_OK', '没有未完成的 worktree run。', '.code-flow/worktrees')];
  const checks = [], registered = worktreeList(root);
  for (const record of records) {
    if (record.status === 'invalid') {
      checks.push(check('WORKTREE_LEDGER_INVALID', 'error', 'fail',
        record.error || 'ledger 无效', record.file, '修复或显式放弃该 run'));
      continue;
    }
    checks.push(...runFindings(root, record.ledger, registered, record));
  }
  return checks.length ? checks : [pass('WORKTREE_OK', 'worktree run 状态可读取。', '.code-flow/worktrees')];
}

function summary(checks) {
  const result = { pass: 0, warning: 0, error: 0, unknown: 0 };
  for (const item of checks) {
    if (item.status === 'pass') result.pass++;
    else if (item.status === 'unknown') result.unknown++;
    if (item.severity === 'warning' && item.status !== 'pass') result.warning++;
    if (item.severity === 'error' && item.status !== 'pass') result.error++;
  }
  return result;
}

function text(checks, totals) {
  return checks.map(item => '[' + item.status.toUpperCase() + '] ' + item.code + ' ' +
    item.message + (item.path ? ' (' + item.path + ')' : '')).join('\n') + '\n' +
    'pass=' + totals.pass + ' warning=' + totals.warning +
    ' error=' + totals.error + ' unknown=' + totals.unknown + '\n';
}

function run(root) {
  const real = f.realpath(root);
  const configured = configChecks(real), settings = configured[0].value;
  const specs = specChecks(real, settings);
  const checks = [
    ...configured[0].checks,
    ...templateChecks(real),
    ...launcherChecks(real),
    ...codexChecks(real),
    ...specs.checks,
    ...taskChecks(real, specs.ids),
    ...worktreeChecks(real)
  ];
  const totals = summary(checks);
  return { schema_version: 1, root: real, ok: totals.error === 0, summary: totals,
    checks, text: text(checks, totals) };
}

module.exports = { run, TEMPLATES, LAUNCHER };
