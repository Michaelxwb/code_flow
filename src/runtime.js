'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');
const pkg = require('../package.json');

function projectRoot(cwd) {
  let current = path.resolve(cwd);
  while (true) {
    if (fs.existsSync(path.join(current, '.code-flow/config.yml'))) return current;
    const parent = path.dirname(current);
    if (parent === current) throw new Error('Run code-flow inside an initialized project.');
    current = parent;
  }
}

function commands(root) {
  const registry = JSON.parse(fs.readFileSync(path.join(root, '.code-flow/runtime-commands.json'), 'utf8'));
  if (registry.schema_version !== 1) throw new Error('Unsupported runtime command contract.');
  return registry.commands;
}

function digest(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function artifactDigest(relative, source) {
  if (relative !== '.opencode/plugins/code-flow/package.json') return digest(source);
  const data = JSON.parse(fs.readFileSync(source, 'utf8'));
  data.version = pkg.version;
  return crypto.createHash('sha256').update(JSON.stringify(data, null, 2) + '\n').digest('hex');
}

function filesUnder(directory, prefix) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__pycache__' || entry.name === '.DS_Store') return [];
    const relative = path.posix.join(prefix, entry.name);
    return entry.isDirectory() ? filesUnder(path.join(directory, entry.name), relative) : [relative];
  });
}

function artifactSources(platforms) {
  const base = path.join(__dirname, 'core/code-flow');
  const sources = { '.code-flow/runtime-commands.json': path.join(base, 'runtime-commands.json') };
  for (const relative of filesUnder(path.join(base, 'scripts'), 'scripts')) {
    sources[`.code-flow/${relative}`] = path.join(base, relative);
  }
  for (const platform of platforms) {
    const adapter = path.join(__dirname, 'adapters', platform);
    const area = platform === 'codex' ? 'skills' : 'commands';
    const destination = platform === 'codex' ? '.agents' : `.${platform}`;
    for (const relative of filesUnder(path.join(adapter, area), area)) {
      sources[`${destination}/${relative}`] = path.join(adapter, relative);
    }
    if (platform === 'opencode') {
      for (const relative of filesUnder(path.join(adapter, 'plugins'), 'plugins')) {
        sources[`.opencode/${relative}`] = path.join(adapter, relative);
      }
    }
  }
  return sources;
}

function hookContracts(platforms) {
  const contracts = {};
  for (const platform of platforms.filter(value => value !== 'opencode')) {
    const name = platform === 'codex' ? 'hooks.json' : 'settings.local.json';
    const source = path.join(__dirname, 'adapters', platform, name);
    contracts[`.${platform}/${name}`] = JSON.parse(fs.readFileSync(source, 'utf8')).hooks;
  }
  return contracts;
}

function writeInstall(root, platforms) {
  const files = Object.fromEntries(Object.entries(artifactSources(platforms))
    .map(([relative, source]) => [relative, artifactDigest(relative, source)]));
  const manifest = { schema_version: 1, version: pkg.version, platforms,
    files, hook_contracts: hookContracts(platforms) };
  const target = path.join(root, '.code-flow/.runtime-install.json');
  fs.writeFileSync(`${target}.tmp`, JSON.stringify(manifest, null, 2) + '\n');
  fs.renameSync(`${target}.tmp`, target);
}

function verifyHooks(root, contracts) {
  for (const [relative, expected] of Object.entries(contracts)) {
    const actual = JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8')).hooks;
    for (const [event, groups] of Object.entries(expected)) {
      for (const group of groups) {
        const candidates = (actual[event] || []).filter(item => (item.matcher || '') === (group.matcher || ''));
        for (const hook of group.hooks) {
          if (!candidates.some(item => item.hooks.some(value => JSON.stringify(value) === JSON.stringify(hook)))) {
            throw new Error(`Managed hook has drifted: ${relative}:${event}`);
          }
        }
      }
    }
  }
}

function verify(root, duringMigration = false) {
  if (!duringMigration && fs.existsSync(path.join(root, '.code-flow/.runtime-migration.lock'))) {
    throw new Error('Runtime migration is in progress or needs recovery.');
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(root, '.code-flow/.runtime-install.json'), 'utf8'));
  const version = fs.readFileSync(path.join(root, '.code-flow/.version'), 'utf8').trim();
  if (manifest.schema_version !== 1 || manifest.version !== version || version !== pkg.version) {
    throw new Error('Runtime and CLI versions differ.');
  }
  if (!manifest.files || Object.keys(manifest.files).length === 0 || !manifest.hook_contracts) {
    throw new Error('Runtime installation manifest is incomplete.');
  }
  const expected = artifactSources(manifest.platforms);
  if (Object.keys(expected).length !== Object.keys(manifest.files).length) {
    throw new Error('Installed artifact set differs from the CLI contract.');
  }
  for (const [relative, source] of Object.entries(expected)) {
    if (manifest.files[relative] !== artifactDigest(relative, source)) {
      throw new Error(`Installed contract differs from the CLI package: ${relative}`);
    }
  }
  for (const [relative, hash] of Object.entries(manifest.files)) {
    const target = path.resolve(root, relative);
    if (!target.startsWith(root + path.sep) || digest(target) !== hash) {
      throw new Error(`Managed runtime artifact has drifted: ${relative}`);
    }
  }
  verifyHooks(root, manifest.hook_contracts);
}

function execute(root, contract, values) {
  try {
    if (values.length === 1 || (values.length === 2 && ['--help', '-h'].includes(values[1]))) {
      const family = Object.keys(contract).filter(command => command.startsWith(values[0] + ' '));
      if (family.length) {
        process.stdout.write(`Usage:\n${family.map(command => `  code-flow ${command} [options]`).join('\n')}\nUse <command> --help for its actual parameters.\n`);
        return 0;
      }
    }
    const key = Object.keys(contract).sort((a, b) => b.length - a.length)
      .find(command => command.split(' ').every((part, index) => values[index] === part));
    if (!key) throw new Error(`Unknown runtime command. Available: ${Object.keys(contract).join(', ')}`);
    const entry = contract[key];
    if (!/^cf_[a-z_]+$/.test(entry.module)) throw new Error('Invalid runtime module in command contract.');
    const script = path.join(root, '.code-flow/scripts', `${entry.module}.py`);
    const args = [...entry.prefix, ...values.slice(key.split(' ').length)];
    const publicName = entry.prefix.length ? key.split(' ').slice(0, -entry.prefix.length).join(' ') : key;
    const result = spawnSync('python3', [script, ...args], {
      cwd: root, stdio: 'inherit', env: { ...process.env,
        CF_RUNTIME_COMMAND: `code-flow ${publicName}`, CF_RUNTIME_ACTION: entry.prefix.join(' ') },
    });
    if (result.error) throw result.error;
    return result.status === null ? 2 : result.status;
  } catch (error) {
    process.stderr.write(`code-flow runtime: ${error.message}\n`);
    return 2;
  }
}

function run(values) {
  let root;
  try {
    root = projectRoot(process.cwd());
  } catch (error) {
    process.stderr.write(`code-flow runtime: ${error.message}\n`);
    return 3;
  }
  try {
    verify(root);
    return execute(root, commands(root), values);
  } catch (error) {
    process.stderr.write(`code-flow installation: ${error.message}\nRepair: code-flow migrate --runtime --dry-run\n`);
    return 3;
  }
}

module.exports = { artifactSources, commands, digest, hookContracts, projectRoot, run, verify, writeInstall };
