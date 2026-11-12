'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const config = require('./config');
const task = require('./task');
const spec = require('./spec');
const doctor = require('./doctor');

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function write(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

function json(file, value) {
  write(file, JSON.stringify(value, null, 2) + '\n');
}

function walk(directory, prefix = '') {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true })
    .sort((left, right) => left.name.localeCompare(right.name))
    .flatMap(entry => {
      const relative = prefix + entry.name;
      return entry.isDirectory() ? walk(path.join(directory, entry.name), relative + '/') : [relative];
    });
}

function copyTree(source, target) {
  if (fs.existsSync(source)) fs.cpSync(source, target, { recursive: true });
}

function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  return result.status === 0 ? result.stdout : 'git unavailable\n';
}

function safe(operation) {
  try { return operation(); } catch (error) {
    return { error: { code: error.code || 'operation_failed', message: error.message } };
  }
}

const README = `code-flow process bundle

events.jsonl           optional CLI/Hook event log (command, args, exit, ms, byte counts, compact summary)
task-status.json       code-flow task status --json
doctor.json            code-flow doctor --json
spec-list.json         code-flow spec list --json
code-flow/specs/       project Spec snapshot
code-flow/tasks/       project task/requirement document snapshot
code-flow/config.json  project config
files.sha256           SHA-256 of Specs and task documents
git-status.txt         working tree status
git-log.txt            recent commits
git-diff-stat.txt      uncommitted diff summary
transcript.jsonl       optional host conversation transcript

Privacy: this bundle can contain project paths, requirement text, and conversation
content. Review it before sharing. The event log does not store rule text or source code.

Analysis targets: command sequence and timing, finish retries, blocked states,
injected/omitted rules and byte counts, spec learn/archive results, task status,
and the requirement documents produced by the workflow.
`;

function collect(root, options = {}) {
  const settings = config.load(root);
  const out = options.out ? path.resolve(options.out) :
    path.join(root, settings.capture.path, 'bundle-' + stamp());
  fs.mkdirSync(out, { recursive: true });
  json(path.join(out, 'task-status.json'), safe(() => task.list(root)));
  json(path.join(out, 'doctor.json'), safe(() => doctor.run(root)));
  json(path.join(out, 'spec-list.json'), safe(() => spec.list(root)));
  const events = process.env.CF_EVENT_LOG || path.join(root, settings.capture.path, 'events.jsonl');
  if (fs.existsSync(events)) fs.copyFileSync(events, path.join(out, 'events.jsonl'));
  copyTree(path.join(root, '.code-flow/specs'), path.join(out, 'code-flow/specs'));
  copyTree(path.join(root, '.code-flow/tasks'), path.join(out, 'code-flow/tasks'));
  if (fs.existsSync(path.join(root, '.code-flow/config.json'))) {
    fs.copyFileSync(path.join(root, '.code-flow/config.json'), path.join(out, 'code-flow/config.json'));
  }
  const documents = [];
  for (const name of ['specs', 'tasks']) {
    const base = path.join(root, '.code-flow', name);
    for (const relative of walk(base)) if (relative.endsWith('.md')) documents.push([base, relative]);
  }
  const lines = documents.sort(([leftBase, left], [rightBase, right]) =>
    (leftBase + '/' + left).localeCompare(rightBase + '/' + right)).map(([base, relative]) => {
    const file = path.join(base, relative);
    const digest = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    return digest + '  ' + path.relative(root, file).split(path.sep).join('/');
  });
  write(path.join(out, 'files.sha256'), lines.join('\n') + (lines.length ? '\n' : ''));
  for (const [name, args] of [['git-status.txt', ['status', '--short']],
    ['git-log.txt', ['log', '--oneline', '-20']], ['git-diff-stat.txt', ['diff', '--stat']]]) {
    write(path.join(out, name), git(root, args));
  }
  let transcript = false;
  if (options.transcript) {
    const file = path.resolve(options.transcript);
    if (fs.existsSync(file)) {
      fs.copyFileSync(file, path.join(out, 'transcript.jsonl'));
      transcript = true;
    }
  }
  write(path.join(out, 'README.txt'), README);
  return { ok: true, action: 'process collect', out, transcript,
    text: 'Process bundle: ' + out + '\n' };
}

module.exports = { collect };
