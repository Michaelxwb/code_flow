'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const config = require('./config');
const adapters = require('./adapters');
const templateRoot = path.join(__dirname, '../templates');
const SKILLS = [
  { name: 'cf-init', path: 'cf-init' },
  { name: 'cf-check', path: 'cf-check' },
  { name: 'cf-spec', path: 'cf-spec' },
  { name: 'cf-task-prd', path: 'cf-task/prd' },
  { name: 'cf-task-align', path: 'cf-task/align' },
  { name: 'cf-task-plan', path: 'cf-task/plan' },
  { name: 'cf-task-start', path: 'cf-task/start' },
  { name: 'cf-task-archive', path: 'cf-task/archive' }
];
const WORKFLOW_TEMPLATES = ['prd.md', 'design-lite.md', 'design-full.md',
  'design-frontend.md', 'scenarios.md', 'task.md', 'project-guidelines.md'];
const LAUNCHER_TEMPLATES = ['bridge.cjs', 'hook.sh', 'hook.cmd', 'hook.ps1'];
function launcherTemplates(platform = process.platform) {
  return platform === 'win32'
    ? ['bridge.cjs', 'hook.cmd', 'hook.ps1', 'hook.sh']
    : ['bridge.cjs', 'hook.sh'];
}

function launcherContent(name, node, entry) {
  const template = fs.readFileSync(path.join(templateRoot, 'launcher', name), 'utf8');
  const sh = value => value.replace(/'/g, "'\\''");
  const cmd = value => value.replace(/%/g, '%%');
  const ps = value => value.replace(/'/g, "''");
  if (name === 'hook.sh') return template.replaceAll('__FIXED_NODE__', sh(node))
    .replaceAll('__FIXED_ENTRY__', sh(entry));
  if (name === 'hook.cmd') return template.replaceAll('__FIXED_NODE__', cmd(node))
    .replaceAll('__FIXED_ENTRY__', cmd(entry));
  if (name === 'hook.ps1') return template.replaceAll('__FIXED_NODE__', ps(node))
    .replaceAll('__FIXED_ENTRY__', ps(entry));
  return template;
}
function installed(root) {
  return Object.entries(adapters.PLATFORMS).filter(([name, value]) => {
    const text = f.readText(f.inside(root, value.hooks));
    if (text === null) return false;
    if (name === 'opencode') return adapters.owned(text);
    const data = f.object(JSON.parse(text), 'platform config');
    return Object.values(data.hooks ?? {}).some(groups => Array.isArray(groups) &&
      groups.some(group => Array.isArray(group.hooks) && group.hooks.some(adapters.managed)));
  }).map(([name]) => name);
}
function add(plans, conflicts, root, relative, after, managed = false) {
  const file = f.inside(root, relative), before = f.readText(file);
  if (managed && before !== null && !adapters.owned(before)) {
    conflicts.push({ path: relative, code: 'file_unmanaged',
      message: 'Preserve/remove unmanaged file before init' });
    return;
  }
  if (before !== after) plans.set(relative, { file, path: relative, before, after });
}
function attempt(conflicts, relative, operation) {
  try { operation(); } catch (error) {
    conflicts.push({ path: relative, code: error.code || 'init_file_failed', message: error.message });
  }
}
function platformPlan(plans, conflicts, root, platform, node, entry) {
  const target = adapters.PLATFORMS[platform];
  const hookFile = f.inside(root, target.hooks);
  const before = f.readText(hookFile);
  if (platform === 'opencode') {
    add(plans, conflicts, root, target.hooks, adapters.plugin(node, entry), true);
    add(plans, conflicts, root, '.opencode/plugins/code-flow/package.json',
      JSON.stringify({ private: true, type: 'module', managed: adapters.MARKER }, null, 2) + '\n', true);
  }
  else attempt(conflicts, target.hooks, () => add(plans, conflicts, root, target.hooks,
    adapters.mergeHooks(before, platform, node, entry)));
  const instruction = fs.readFileSync(path.join(templateRoot, 'instructions.md'), 'utf8');
  attempt(conflicts, target.instructions, () => add(plans, conflicts, root, target.instructions,
    adapters.instructions(f.readText(f.inside(root, target.instructions)), instruction)));
  for (const skill of SKILLS) {
    const name = platform === 'codex' ? skill.name : skill.path;
    const relative = target.skills + '/' + name + (platform === 'codex' ? '/SKILL.md' : '.md');
    add(plans, conflicts, root, relative,
      fs.readFileSync(path.join(templateRoot, 'skills', skill.name + '.md'), 'utf8'), true);
  }
  if (platform === 'codex') {
    const relative = '.codex/config.toml';
    attempt(conflicts, relative, () => add(plans, conflicts, root, relative,
      adapters.codexConfig(f.readText(f.inside(root, relative)))));
  }
}
function dedupePlans(plans, conflicts) {
  const byReal = new Map();
  for (const item of [...plans.values()]) {
    let real = item.file, symlink = false;
    try {
      real = fs.realpathSync(item.file);
      symlink = fs.lstatSync(item.file).isSymbolicLink();
    } catch (_) { /* new file */ }
    const previous = byReal.get(real);
    if (!previous) { byReal.set(real, { item, symlink }); continue; }
    if (previous.item.after !== item.after) {
      conflicts.push({ path: item.path, code: 'shared_instruction_conflict',
        message: 'Shared instruction file has conflicting planned content' });
      plans.delete(item.path);
      continue;
    }
    if (previous.symlink && !symlink) {
      plans.delete(previous.item.path);
      byReal.set(real, { item, symlink });
    } else plans.delete(item.path);
  }
}

function plan(root, options = {}) {
  const dataDir = f.inside(root, '.code-flow'), configuration = f.inside(root, '.code-flow/config.json');
  const before = f.readText(configuration, 65536);
  f.demand(before !== null || !fs.existsSync(dataDir) || fs.readdirSync(dataDir).length === 0,
    'directory_format', 'Nonempty .code-flow without v1 config; preserve it outside the project before init');
  if (before !== null) config.load(root);
  const platforms = installed(root);
  if (options.platform === 'all') {
    for (const name of Object.keys(adapters.PLATFORMS)) if (!platforms.includes(name)) platforms.push(name);
  } else if (options.platform) {
    f.demand(Object.hasOwn(adapters.PLATFORMS, options.platform), 'platform_invalid', 'Unknown platform: ' + options.platform);
    if (!platforms.includes(options.platform)) platforms.push(options.platform);
  }
  f.demand(platforms.length > 0, 'platform_required', 'First init requires --platform');
  const plans = new Map(), conflicts = [];
  if (before === null) add(plans, conflicts, root, '.code-flow/config.json',
    fs.readFileSync(path.join(templateRoot, 'config.json'), 'utf8'));
  for (const name of WORKFLOW_TEMPLATES) {
    add(plans, conflicts, root, '.code-flow/templates/' + name,
      fs.readFileSync(path.join(templateRoot, 'workflow', name), 'utf8'));
  }
  const node = options.node ?? process.execPath, entry = options.entry ?? path.resolve(__dirname, '../bin/code-flow.js');
  for (const name of launcherTemplates()) {
    add(plans, conflicts, root, '.code-flow/launcher/' + name, launcherContent(name, node, entry));
  }
  for (const platform of platforms.sort()) platformPlan(plans, conflicts, root, platform, node, entry);
  dedupePlans(plans, conflicts);
  return { plans: [...plans.values()], platforms, conflicts };
}
function localPlatforms(root) {
  const detected = new Set(installed(root));
  const roots = { claude: ['.claude'], costrict: ['.costrict'],
    codex: ['.codex', '.agents'], opencode: ['.opencode'] };
  for (const [name, dirs] of Object.entries(roots)) {
    if (dirs.some(directory => fs.existsSync(f.inside(root, directory)))) detected.add(name);
  }
  f.demand(detected.size > 0, 'platform_missing',
    'No supported platform detected; run code-flow init --platform=...');
  return [...detected].sort();
}

function nodePlan(root, options = {}) {
  const node = options.node ?? process.execPath;
  const entry = options.entry ?? path.resolve(__dirname, '../bin/code-flow.js');
  const plans = new Map(), conflicts = [], platforms = localPlatforms(root);
  for (const name of launcherTemplates()) {
    add(plans, conflicts, root, '.code-flow/launcher/' + name, launcherContent(name, node, entry));
  }
  for (const platform of platforms) {
    const target = adapters.PLATFORMS[platform], before = f.readText(f.inside(root, target.hooks));
    if (platform === 'opencode') {
      add(plans, conflicts, root, target.hooks, adapters.plugin(node, entry), true);
      add(plans, conflicts, root, '.opencode/plugins/code-flow/package.json',
        JSON.stringify({ private: true, type: 'module', managed: adapters.MARKER }, null, 2) + '\n', true);
    } else {
      if (platform === 'codex') continue;
      attempt(conflicts, target.hooks, () => add(plans, conflicts, root, target.hooks,
        adapters.mergeHooks(before, platform, node, entry)));
    }
  }
  return { plans: [...plans.values()], platforms, conflicts };
}

async function node(root, options = {}) {
  config.load(root);
  const build = () => nodePlan(root, options);
  const execute = prepared => {
    if (!options.dryRun) {
      for (const item of prepared.plans) f.atomicWrite(item.file, item.after, item.before);
      fs.mkdirSync(f.inside(root, '.code-flow/launcher'), { recursive: true });
      if (prepared.platforms.includes('opencode'))
        fs.mkdirSync(f.inside(root, '.opencode/plugins/code-flow'), { recursive: true });
    }
    return { ok: prepared.conflicts.length === 0, action: 'node', dry_run: Boolean(options.dryRun),
      platforms: prepared.platforms, conflicts: prepared.conflicts,
      changes: prepared.plans.map(item => ({ path: item.path,
        action: item.before === null ? 'create' : 'update' })),
      next: prepared.conflicts.length ? 'Resolve reported file conflicts, then re-run code-flow node.' :
        'Reload platform configuration.' };
  };
  if (options.dryRun) return execute(build());
  return f.withLock(root, 'write', async () => execute(build()));
}

async function init(root, options = {}) {
  const build = () => plan(root, options);
  const execute = prepared => {
    if (!options.dryRun) {
      for (const item of prepared.plans) f.atomicWrite(item.file, item.after, item.before);
      for (const directory of ['.code-flow/specs', '.code-flow/tasks',
        '.code-flow/templates', '.code-flow/launcher'])
        fs.mkdirSync(f.inside(root, directory), { recursive: true });
    }
    return { ok: prepared.conflicts.length === 0, action: 'init', dry_run: Boolean(options.dryRun),
      platforms: prepared.platforms, conflicts: prepared.conflicts,
      changes: prepared.plans.map(item => ({ path: item.path,
        action: item.before === null ? 'create' : 'update' })),
      next: prepared.conflicts.length ? 'Resolve reported file conflicts, then re-run init.' :
        prepared.platforms.includes('codex') ? 'Review/trust changed hooks in Codex /hooks.' : 'Reload platform configuration.' };
  };
  if (options.dryRun) return execute(build());
  return f.withLock(root, 'write', async () => execute(build()));
}
module.exports = { init, node, plan, installed, WORKFLOW_TEMPLATES, LAUNCHER_TEMPLATES, launcherTemplates };
