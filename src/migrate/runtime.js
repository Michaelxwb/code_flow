'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const runtime = require('../runtime');
const pkg = require('../../package.json');

function guardVersion(root) {
  const version = fs.readFileSync(path.join(root, '.code-flow/.version'), 'utf8').trim();
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`Invalid installed runtime version: ${version}`);
  const installed = version.split('.').map(Number);
  const target = pkg.version.split('.').map(Number);
  for (let index = 0; index < 3; index++) {
    if (installed[index] > target[index]) throw new Error(`Refusing runtime downgrade from ${version} to ${pkg.version}; update the CLI.`);
    if (installed[index] < target[index]) return;
  }
}

function walk(root, directory = '') {
  const target = path.join(root, directory);
  if (!fs.existsSync(target)) return [];
  return fs.readdirSync(target, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__pycache__') return [];
    const relative = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(root, relative) : [relative];
  });
}

function platforms(root) {
  const markers = { claude: '.claude/commands/cf-init.md', codex: '.agents/skills/cf-init/SKILL.md',
    costrict: '.costrict/commands/cf-init.md', opencode: '.opencode/commands/cf-init.md' };
  const found = Object.entries(markers).filter(([, marker]) => fs.existsSync(path.join(root, marker))).map(([name]) => name);
  if (!found.length) throw new Error('No installed platform found; run code-flow init first.');
  return found;
}

function inputs(root, installed) {
  const core = path.join(__dirname, '../core/code-flow');
  const files = [...Object.keys(runtime.artifactSources(installed)), ...walk(core).map(file => `.code-flow/${file}`),
    '.code-flow/scripts/cf_codex_user_prompt_hook.py',
    '.code-flow/.version', '.code-flow/.adapter-versions.json', '.code-flow/.runtime-install.json',
    '.code-flow/.gitignore', 'AGENTS.md', 'CLAUDE.md', 'opencode.json', '.codex/config.toml',
    ...Object.keys(runtime.hookContracts(installed))];
  return [...new Set(files)].filter(file => fs.existsSync(path.join(root, file)));
}

function copyFile(root, target, relative) {
  const destination = path.join(target, relative);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(path.join(root, relative), destination);
}

function writeJson(file, value) {
  fs.writeFileSync(`${file}.tmp`, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(`${file}.tmp`, file);
}

function prepare(root, locked = false) {
  guardVersion(root);
  const installed = platforms(root);
  const id = `runtime-${Date.now()}-${process.pid}`;
  const workspace = path.join(root, '.code-flow/migrations', id);
  const staging = path.join(workspace, 'staging');
  fs.mkdirSync(staging, { recursive: true });
  fs.mkdirSync(path.join(workspace, 'backup'));
  const original = inputs(root, installed);
  const sources = Object.fromEntries(original.map(file => [file, runtime.digest(path.join(root, file))]));
  const journal = { schema_version: 1, id, root, platforms: installed,
    status: 'staging', sources, hashes: {}, deletions: [], written: [] };
  writeJson(path.join(workspace, 'journal.json'), journal);
  if (locked) writeJson(path.join(root, '.code-flow/.runtime-migration.lock/owner.json'), { pid: process.pid, id });
  for (const relative of original) {
    copyFile(root, staging, relative);
    copyFile(root, path.join(workspace, 'backup'), relative);
  }
  writeJson(path.join(staging, '.runtime-stage.json'), { root, id });
  for (const platform of installed) {
    const result = spawnSync(process.execPath, [path.join(__dirname, '../cli.js'), 'init', `--platform=${platform}`], {
      cwd: staging, encoding: 'utf8', env: { ...process.env, CODE_FLOW_RUNTIME_STAGE: staging },
    });
    if (result.error || result.status !== 0) throw new Error(`Runtime staging failed: ${result.error || result.stderr || result.stdout}`);
  }
  runtime.verify(staging);
  const targets = walk(staging).filter(file => file !== '.runtime-stage.json' && !file.startsWith('.code-flow/backups/'));
  const hashes = Object.fromEntries(targets.map(file => [file, runtime.digest(path.join(staging, file))]));
  journal.deletions = original.filter(file => !fs.existsSync(path.join(staging, file)));
  journal.hashes = hashes;
  journal.status = 'prepared';
  writeJson(path.join(workspace, 'journal.json'), journal);
  return { workspace, journal, staging };
}

function restore(workspace, journal) {
  const order = [...journal.written].reverse();
  for (const relative of order) {
    const target = path.join(journal.root, relative);
    const backup = path.join(workspace, 'backup', relative);
    if (fs.existsSync(backup)) copyFile(path.join(workspace, 'backup'), journal.root, relative);
    else fs.rmSync(target, { force: true });
  }
  journal.status = 'rolled_back';
  writeJson(path.join(workspace, 'journal.json'), journal);
  return { status: journal.status, migration_id: journal.id };
}

function apply(root) {
  let repairReason;
  try {
    runtime.verify(root, true);
    return { status: 'already_migrated' };
  } catch (error) {
    repairReason = error.message;
  }
  const { workspace, journal, staging } = prepare(root, true);
  try {
    for (const [relative, hash] of Object.entries(journal.sources)) {
      if (runtime.digest(path.join(root, relative)) !== hash) throw new Error(`Source changed during staging: ${relative}`);
    }
    journal.status = 'applying';
    writeJson(path.join(workspace, 'journal.json'), journal);
    const targets = Object.keys(journal.hashes).filter(file => file !== '.code-flow/.version');
    for (const relative of journal.deletions) {
      journal.written.push(relative);
      writeJson(path.join(workspace, 'journal.json'), journal);
      fs.rmSync(path.join(root, relative));
    }
    targets.push('.code-flow/.version');
    for (const relative of targets) {
      if (!journal.sources[relative] && fs.existsSync(path.join(root, relative))) throw new Error(`New target appeared: ${relative}`);
      if (runtime.digest(path.join(staging, relative)) !== journal.hashes[relative]) throw new Error(`Staging drift: ${relative}`);
      journal.written.push(relative);
      writeJson(path.join(workspace, 'journal.json'), journal);
      copyFile(staging, root, relative);
    }
    runtime.verify(root, true);
    journal.status = 'committed';
    writeJson(path.join(workspace, 'journal.json'), journal);
    return { status: journal.status, migration_id: journal.id, platforms: journal.platforms, repair_reason: repairReason };
  } catch (error) {
    const result = restore(workspace, journal);
    return { ...result, error: error.message };
  }
}

function rollback(root, id) {
  if (!/^runtime-\d+-\d+$/.test(id)) throw new Error('Invalid runtime migration id.');
  const workspace = path.join(root, '.code-flow/migrations', id);
  const journal = JSON.parse(fs.readFileSync(path.join(workspace, 'journal.json'), 'utf8'));
  if (journal.root !== root) throw new Error('Migration belongs to a different project.');
  if (journal.status === 'rolled_back') return { status: 'rolled_back', migration_id: id };
  if (journal.status === 'committed') {
    for (const [relative, hash] of Object.entries(journal.hashes)) {
      if (runtime.digest(path.join(root, relative)) !== hash) throw new Error(`Rollback would overwrite subsequent changes: ${relative}`);
    }
  }
  return restore(workspace, journal);
}

function withLock(root, values) {
  const lock = path.join(root, '.code-flow/.runtime-migration.lock');
  try {
    fs.mkdirSync(lock);
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    const owner = JSON.parse(fs.readFileSync(path.join(lock, 'owner.json'), 'utf8'));
    let live = true;
    try { process.kill(owner.pid, 0); } catch (signalError) {
      if (signalError.code !== 'ESRCH') throw signalError;
      live = false;
    }
    if (live) throw new Error('Another runtime migration is running.');
    if (values[0] !== '--rollback' || values[1] !== owner.id) {
      throw new Error(`Interrupted migration; run code-flow migrate --runtime --rollback ${owner.id}`);
    }
    fs.rmSync(lock, { recursive: true });
    fs.mkdirSync(lock);
  }
  writeJson(path.join(lock, 'owner.json'), { pid: process.pid, id: '' });
  try {
    return values[0] === '--apply' ? apply(root) : rollback(root, values[1]);
  } finally {
    fs.rmSync(lock, { recursive: true });
  }
}

function run(root, values) {
  if (values.length === 1 && values[0] === '--dry-run') {
    const { workspace, journal } = prepare(root);
    fs.rmSync(path.join(workspace, 'staging'), { recursive: true });
    fs.rmSync(path.join(workspace, 'backup'), { recursive: true });
    journal.status = 'previewed';
    writeJson(path.join(workspace, 'journal.json'), journal);
    return { status: journal.status, migration_id: journal.id, platforms: journal.platforms,
      files: Object.keys(journal.hashes), apply: 'code-flow migrate --runtime --apply' };
  }
  if (values.length === 1 && values[0] === '--apply') return withLock(root, values);
  if (values.length === 2 && values[0] === '--rollback') return withLock(root, values);
  throw new Error('Choose --dry-run, --apply, or --rollback <id>.');
}

module.exports = { run };
