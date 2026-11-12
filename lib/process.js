'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const config = require('./config');
const task = require('./task');
const spec = require('./spec');
const doctor = require('./doctor');
const init = require('./init');

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

events.jsonl           optional CLI/Hook event log (command, args, exit, ms, byte counts, summary)
environment.json       OS/Node/CLI version, git head, platforms, capture settings
summary.json           aggregated command, timing, hook injection and failure summary
worktree-events.jsonl  merged worker events with source/run_id/task provenance
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
content. Review it before sharing. The event log does not store rule text, source code,
or full prompt text; it stores bounded metadata, refs and hashes.

Analysis targets: command sequence and timing, hook task/session/emitted/omitted refs,
finish test results and provenance, blocked states, spec learn/archive results,
task status, failures, and the requirement documents produced by the workflow.
`;

function readEvents(file) {
  const events = [], invalid = [];
  if (!fs.existsSync(file)) return { events, invalid };
  for (const [index, line] of fs.readFileSync(file, 'utf8').split('\n').entries()) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch (error) {
      invalid.push({ line: index + 1, error: error.message });
    }
  }
  return { events, invalid };
}

function countRefs(target, value) {
  for (const ref of Array.isArray(value) ? value : []) {
    if (typeof ref === 'string') target[ref] = (target[ref] || 0) + 1;
  }
}

function summarizeEvents(events, invalid, taskStatus, worktreeCount = 0) {
  const commands = {}, exits = {};
  const hook = { count: 0, emitted: 0, omitted: 0, emitted_refs: {}, omitted_refs: {}, tasks: [] };
  const failures = [];
  let first = null, last = null, totalMs = 0, maxMs = 0;
  for (const event of events) {
    commands[event.command] = (commands[event.command] || 0) + 1;
    exits[event.exit] = (exits[event.exit] || 0) + 1;
    if (typeof event.ms === 'number') { totalMs += event.ms; maxMs = Math.max(maxMs, event.ms); }
    if (typeof event.at === 'string') { first ||= event.at; last = event.at; }
    const summary = event.summary || {};
    if (event.command === 'hook prompt') {
      hook.count++;
      hook.emitted += Number(summary.emitted) || 0;
      hook.omitted += Number(summary.omitted) || 0;
      countRefs(hook.emitted_refs, summary.emitted_refs);
      countRefs(hook.omitted_refs, summary.omitted_refs);
      if (summary.task && !hook.tasks.includes(summary.task)) hook.tasks.push(summary.task);
    }
    if (event.exit !== 0 && failures.length < 50) failures.push({
      at: event.at, command: event.command, exit: event.exit, ms: event.ms,
      source: event.source || 'coordinator', run_id: event.run_id || null, task: event.task || null,
      error: summary.error ?? null, message: summary.error_message ?? null,
    });
  }
  const items = Array.isArray(taskStatus?.items) ? taskStatus.items : [];
  return {
    events: { total: events.length, invalid: invalid.length, first_at: first, last_at: last,
      coordinator: events.filter(event => event.source !== 'worktree').length,
      worktree: worktreeCount },
    commands, exits, duration_ms_total: totalMs, duration_ms_max: maxMs,
    hook_prompts: { ...hook, emitted_refs: Object.fromEntries(Object.entries(hook.emitted_refs).sort()),
      omitted_refs: Object.fromEntries(Object.entries(hook.omitted_refs).sort()) },
    task_status: { total: items.length,
      done: items.filter(item => item.status === 'done').length,
      in_progress: items.filter(item => item.status === 'in-progress').length,
      draft: items.filter(item => item.status === 'draft').length,
      blocked: items.filter(item => item.status === 'blocked').length },
    failures,
    invalid_lines: invalid.slice(0, 20),
  };
}

function worktreeEventFiles(root) {
  const base = path.join(root, '.code-flow/worktrees');
  if (!fs.existsSync(base)) return [];
  const files = [];
  for (const run of fs.readdirSync(base, { withFileTypes: true })) {
    if (!run.isDirectory()) continue;
    const runDir = path.join(base, run.name);
    for (const worker of fs.readdirSync(runDir, { withFileTypes: true })) {
      if (!worker.isDirectory() || !/^TASK-\d+$/.test(worker.name)) continue;
      const file = path.join(runDir, worker.name, '.code-flow/process/events.jsonl');
      if (fs.existsSync(file)) files.push({ file, run_id: run.name, task: worker.name,
        worktree: '.code-flow/worktrees/' + run.name + '/' + worker.name });
    }
  }
  return files;
}

function eventKey(event) {
  if (typeof event.event_id === 'string' && event.event_id) return event.event_id;
  return JSON.stringify([event.at, event.command, event.args, event.cwd, event.exit,
    event.run_id, event.task, event.worktree]);
}

function mergeEvents(existing, incoming) {
  const merged = new Map();
  for (const event of [...existing, ...incoming]) {
    const key = eventKey(event);
    if (!merged.has(key)) merged.set(key, event);
  }
  return [...merged.values()].sort((left, right) =>
    String(left.at || '').localeCompare(String(right.at || '')));
}

function readWorktreeEvents(root) {
  const events = [];
  for (const source of worktreeEventFiles(root)) {
    const { events: found } = readEvents(source.file);
    for (const event of found) events.push({ ...event, source: 'worktree',
      run_id: event.run_id || source.run_id, task: event.task || source.task,
      worktree: event.worktree || source.worktree });
  }
  return events;
}

function writeBundle(bundle, root, settings, events, worktreeEvents, taskStatus, transcript, clean = true) {
  if (clean) fs.rmSync(bundle, { recursive: true, force: true });
  fs.mkdirSync(bundle, { recursive: true });
  json(path.join(bundle, 'task-status.json'), taskStatus);
  json(path.join(bundle, 'doctor.json'), safe(() => doctor.run(root)));
  json(path.join(bundle, 'spec-list.json'), safe(() => spec.list(root)));
  if (fs.existsSync(events)) {
    const target = path.join(bundle, 'events.jsonl');
    if (path.resolve(events) !== path.resolve(target)) fs.copyFileSync(events, target);
  }
  fs.writeFileSync(path.join(bundle, 'worktree-events.jsonl'),
    worktreeEvents.map(event => JSON.stringify(event)).join('\n') + (worktreeEvents.length ? '\n' : ''));
  const head = git(root, ['rev-parse', 'HEAD']).trim();
  json(path.join(bundle, 'environment.json'), environment(root, settings, head));
  json(path.join(bundle, 'summary.json'),
    summarizeEvents([...readEvents(events).events, ...worktreeEvents],
      readEvents(events).invalid, taskStatus, worktreeEvents.length));
  copyTree(path.join(root, '.code-flow/specs'), path.join(bundle, 'code-flow/specs'));
  copyTree(path.join(root, '.code-flow/tasks'), path.join(bundle, 'code-flow/tasks'));
  if (fs.existsSync(path.join(root, '.code-flow/config.json'))) {
    fs.copyFileSync(path.join(root, '.code-flow/config.json'), path.join(bundle, 'code-flow/config.json'));
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
  write(path.join(bundle, 'files.sha256'), lines.join('\n') + (lines.length ? '\n' : ''));
  for (const [name, args] of [['git-status.txt', ['status', '--short']],
    ['git-log.txt', ['log', '--oneline', '-20']], ['git-diff-stat.txt', ['diff', '--stat']]]) {
    write(path.join(bundle, name), git(root, args));
  }
  if (transcript) fs.copyFileSync(transcript, path.join(bundle, 'transcript.jsonl'));
  write(path.join(bundle, 'README.txt'), README);
}

function environment(root, settings, head) {
  return {
    code_flow_version: require('../package.json').version,
    node: process.version, platform: process.platform, arch: process.arch,
    cwd: root, git_head: /^[0-9a-f]{7,40}$/.test(head) ? head : null,
    platforms: safe(() => init.installed(root)), capture: settings.capture,
  };
}

function collect(root, options = {}) {
  const settings = config.load(root);
  const home = options.out ? path.resolve(options.out) : path.join(root, settings.capture.path);
  const bundle = options.out ? home : path.join(home, 'analysis');
  fs.mkdirSync(home, { recursive: true });
  const taskStatus = safe(() => task.list(root));
  const events = process.env.CF_EVENT_LOG || path.join(root, settings.capture.path, 'events.jsonl');
  const stableWorktree = path.join(home, 'worktree-events.jsonl');
  const previousWorktree = readEvents(stableWorktree).events;
  const worktreeEvents = mergeEvents(previousWorktree, readWorktreeEvents(root));
  const parsed = readEvents(events);
  const head = git(root, ['rev-parse', 'HEAD']).trim();
  json(path.join(home, 'environment.json'), environment(root, settings, head));
  json(path.join(home, 'summary.json'), summarizeEvents([...parsed.events, ...worktreeEvents],
    parsed.invalid, taskStatus, worktreeEvents.length));
  write(path.join(home, 'worktree-events.jsonl'),
    worktreeEvents.map(event => JSON.stringify(event)).join('\n') + (worktreeEvents.length ? '\n' : ''));
  let transcript = false;
  if (options.transcript) {
    const file = path.resolve(options.transcript);
    if (fs.existsSync(file)) transcript = file;
  }
  writeBundle(bundle, root, settings, events, worktreeEvents, taskStatus, transcript, !options.out);
  return { ok: true, action: 'process collect', out: bundle, home, transcript: Boolean(transcript),
    worktree_events: worktreeEvents.length,
    text: 'Process bundle: ' + bundle + '\n' };
}

module.exports = { collect };
