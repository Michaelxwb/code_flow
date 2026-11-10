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
  'design-frontend.md', 'scenarios.md', 'task.md'];
const LAUNCHER_TEMPLATES = ['bridge.cjs', 'hook.sh', 'hook.cmd', 'hook.ps1'];

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
function add(plans, root, relative, after, managed = false) {
  const file = f.inside(root, relative), before = f.readText(file);
  f.demand(!managed || before === null || adapters.owned(before),
    'file_unmanaged', 'Preserve/remove unmanaged file before init: ' + relative);
  if (before !== after) plans.set(relative, { file, path: relative, before, after });
}
function platformPlan(plans, root, platform, node, entry) {
  const target = adapters.PLATFORMS[platform];
  const hookFile = f.inside(root, target.hooks);
  const before = f.readText(hookFile);
  if (platform === 'opencode') {
    add(plans, root, target.hooks, adapters.plugin(node, entry), true);
    add(plans, root, '.opencode/plugins/code-flow/package.json',
      JSON.stringify({ private: true, type: 'module', managed: adapters.MARKER }, null, 2) + '\n', true);
  }
  else add(plans, root, target.hooks, adapters.mergeHooks(before, platform, node, entry));
  const instruction = fs.readFileSync(path.join(templateRoot, 'instructions.md'), 'utf8');
  add(plans, root, target.instructions, adapters.instructions(f.readText(f.inside(root, target.instructions)), instruction));
  for (const skill of SKILLS) {
    const name = platform === 'codex' ? skill.name : skill.path;
    const relative = target.skills + '/' + name + (platform === 'codex' ? '/SKILL.md' : '.md');
    add(plans, root, relative, fs.readFileSync(path.join(templateRoot, 'skills', skill.name + '.md'), 'utf8'), true);
  }
  if (platform === 'codex') {
    const relative = '.codex/config.toml';
    add(plans, root, relative, adapters.codexConfig(f.readText(f.inside(root, relative))));
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
  const plans = new Map();
  if (before === null) add(plans, root, '.code-flow/config.json', fs.readFileSync(path.join(templateRoot, 'config.json'), 'utf8'));
  for (const name of WORKFLOW_TEMPLATES) {
    add(plans, root, '.code-flow/templates/' + name,
      fs.readFileSync(path.join(templateRoot, 'workflow', name), 'utf8'));
  }
  const node = options.node ?? process.execPath, entry = options.entry ?? path.resolve(__dirname, '../bin/code-flow.js');
  for (const name of LAUNCHER_TEMPLATES) {
    add(plans, root, '.code-flow/launcher/' + name, launcherContent(name, node, entry));
  }
  for (const platform of platforms.sort()) platformPlan(plans, root, platform, node, entry);
  return { plans: [...plans.values()], platforms };
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
    return { ok: true, action: 'init', dry_run: Boolean(options.dryRun),
      platforms: prepared.platforms, changes: prepared.plans.map(item => ({ path: item.path,
        action: item.before === null ? 'create' : 'update' })),
      next: prepared.platforms.includes('codex') ? 'Review/trust changed hooks in Codex /hooks.' : 'Reload platform configuration.' };
  };
  if (options.dryRun) return execute(build());
  return f.withLock(root, 'write', async () => execute(build()));
}
module.exports = { init, plan, installed };
