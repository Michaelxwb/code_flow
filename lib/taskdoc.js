'use strict';
const path = require('node:path');
const f = require('./fs');
const fm = require('./frontmatter');
const config = require('./config');
const glob = require('./glob');

const STATES = ['draft', 'in-progress', 'done', 'blocked'];
const RESERVED_ENV = new Set(['CF_WORKTREE_ID', 'CF_TASK_ID', 'CF_TASK_IDS', 'CF_RUN_ID',
  'CF_PORT_OFFSET', 'CF_DB_SUFFIX']);
const FIELDS = {
  Status: 'status', Depends: 'depends', Source: 'source', Scenarios: 'scenarios',
  'Spec-Refs': 'specRefs', Paths: 'paths', E2E: 'e2e',
  'Skip-Tests': 'skipTests', 'Skip-Reason': 'skipReason'
};

function heading(line) {
  const match = /^##[ \t]+(TASK-\d+):[ \t]*(.*)$/.exec(line.replace(/\r$/, ''));
  return match ? { id: match[1], title: match[2].trim() } : null;
}

function splitSections(body) {
  const lines = body.split('\n');
  const headings = [];
  let fence = null, offset = 0;
  for (const line of lines) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
    } else if (!fence && /^##[ \t]/.test(line)) {
      const parsed = heading(line);
      if (!parsed) throw new f.FlowError('task_section_invalid', 'Unexpected section heading: ' + line.trim(), 2);
      headings.push({ ...parsed, start: offset });
    }
    offset += line.length + 1;
  }
  if (!headings.length) throw new f.FlowError('tasks_missing', 'Task document has no TASK sections', 2);
  const preamble = body.slice(0, headings[0].start);
  const sections = headings.map((item, index) => ({
    ...item,
    text: body.slice(item.start, index + 1 < headings.length ? headings[index + 1].start : body.length)
  }));
  return { preamble, sections };
}

function fieldMap(text) {
  const values = {};
  let fence = null;
  for (const line of text.split('\n')) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      continue;
    }
    if (fence) continue;
    const match = /^- \*\*([^*]+)\*\*:[ \t]*(.*)$/.exec(line.replace(/\r$/, ''));
    if (match && Object.hasOwn(FIELDS, match[1])) values[FIELDS[match[1]]] = match[2].trim();
  }
  return values;
}

function subsection(text, name) {
  const lines = text.split('\n');
  let start = -1, fence = null;
  for (let index = 0; index < lines.length; index++) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(lines[index]);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      continue;
    }
    if (fence) continue;
    if (start < 0 && lines[index].replace(/\r$/, '') === '### ' + name) start = index + 1;
    else if (start >= 0 && /^###[ \t]/.test(lines[index])) return lines.slice(start, index).join('\n');
  }
  return start < 0 ? null : lines.slice(start).join('\n');
}

function jsonArray(text, name) {
  if (text === null) return [];
  const match = /```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```/.exec(text);
  if (!match) throw new f.FlowError('task_json_missing', 'Missing JSON block in ### ' + name, 2);
  let value;
  try { value = JSON.parse(match[1]); } catch (error) {
    throw new f.FlowError('task_json_invalid', 'Invalid JSON in ### ' + name + ': ' + error.message, 2);
  }
  f.demand(Array.isArray(value), 'task_json_invalid', '### ' + name + ' must be a JSON array');
  return value;
}

function parseList(value) {
  return [...new Set(String(value ?? '').split(/[,\s]+/).map(item => item.trim()).filter(Boolean))];
}

function validateTests(tests) {
  f.demand(Array.isArray(tests), 'task_tests', 'Task tests must be an array');
  const ids = new Set();
  for (const test of tests) {
    f.object(test, 'test'); f.string(test.id, 'test.id');
    f.demand(!ids.has(test.id), 'test_duplicate', 'Duplicate test ID: ' + test.id); ids.add(test.id);
    f.demand((test.argv !== undefined) !== (test.run !== undefined), 'test_command', 'Exactly one of argv/run required');
    if (test.argv !== undefined) {
      f.demand(Array.isArray(test.argv) && test.argv.length > 0 &&
        test.argv.every(arg => typeof arg === 'string' && !arg.includes('\0')), 'test_command', 'argv must be strings');
      f.string(test.argv[0], 'argv executable');
    } else f.string(test.run, 'test.run');
    if (test.cwd !== undefined) f.string(test.cwd, 'test.cwd');
    if (test.timeout !== undefined) f.positive(test.timeout, 'test.timeout');
    if (test.parallel !== undefined) f.demand(typeof test.parallel === 'boolean', 'test_parallel', 'parallel must be boolean');
    if (test.group !== undefined) f.string(test.group, 'test.group');
    if (test.env !== undefined) {
      f.object(test.env, 'test.env');
      for (const [key, value] of Object.entries(test.env)) {
        f.demand(/^[A-Za-z_][A-Za-z0-9_]*$/.test(key), 'test_env', 'Invalid test env name: ' + key);
        f.demand(typeof value === 'string' && !value.includes('\0'), 'test_env',
          'Test env values must be strings: ' + key);
        f.demand(!RESERVED_ENV.has(key), 'test_env', 'Test env cannot override ' + key);
      }
    }
  }
  return tests;
}

function validateTask(task) {
  f.demand(/^TASK-\d+$/.test(task.id), 'task_identity', 'Invalid TASK ID: ' + task.id);
  f.demand(STATES.includes(task.status), 'task_status', 'Invalid Task status: ' + task.status);
  for (const dep of task.depends) f.demand(/^TASK-\d+$/.test(dep) && dep !== task.id,
    'task_depends', 'Invalid dependency for ' + task.id + ': ' + dep);
  task.scenarios.forEach(id => f.demand(/^[SEB]-\d+$/.test(id), 'task_scenario', 'Invalid scenario ID: ' + id));
  task.specRefs.forEach(config.reference);
  task.paths.forEach(glob.compile);
  validateTests(task.tests);
  f.demand(typeof task.skipTests === 'boolean', 'task_skip', 'skip_tests must be boolean');
  if (task.skipTests) f.string(task.skipReason, 'skip_reason');
  if (task.e2e) f.string(task.e2e, 'e2e');
  f.demand(Array.isArray(task.specDelta), 'delta_invalid', 'Spec Delta must be an array');
  return task;
}

function parseTask(section) {
  const values = fieldMap(section.text);
  if (values.skipTests !== undefined && values.skipTests !== '') {
    f.demand(['true', 'false'].includes(values.skipTests), 'task_skip',
      'Skip-Tests must be true or false');
  }
  const tests = jsonArray(subsection(section.text, 'Tests'), 'Tests');
  const specDelta = jsonArray(subsection(section.text, 'Spec Delta'), 'Spec Delta');
  const task = {
    id: section.id, title: section.title,
    status: values.status || '',
    depends: parseList(values.depends),
    source: values.source || '',
    scenarios: parseList(values.scenarios),
    specRefs: parseList(values.specRefs),
    paths: parseList(values.paths),
    e2e: values.e2e || '',
    skipTests: values.skipTests === 'true',
    skipReason: values.skipReason || '',
    tests, specDelta, text: section.text
  };
  return validateTask(task);
}

function validateSet(tasks) {
  const ids = new Set();
  for (const task of tasks) {
    f.demand(!ids.has(task.id), 'task_duplicate', 'Duplicate TASK ID: ' + task.id);
    ids.add(task.id);
  }
  for (const task of tasks) {
    for (const dep of task.depends) {
      f.demand(ids.has(dep), 'task_depends', task.id + ' depends on missing ' + dep);
    }
  }
}

function parse(raw, file) {
  const document = fm.parse(raw);
  f.demand(document.meta.version === 1, 'task_version', 'Task document version must be 1');
  f.string(document.meta.requirement, 'task requirement');
  f.demand(path.basename(file, '.md') === document.meta.requirement,
    'task_requirement', 'Task document name must match requirement: ' + document.meta.requirement);
  const split = splitSections(document.body);
  const tasks = split.sections.map(parseTask);
  validateSet(tasks);
  return { ...document, tasks, preamble: split.preamble };
}

function taskFrom(document, task) {
  return { ...task, body: task.text, document, file: document.file, relative: document.relative,
    raw: document.raw, meta: task, documentMeta: document.meta };
}

function find(document, taskId) {
  const task = document.tasks.find(item => item.id === taskId);
  f.demand(task, 'task_missing', 'Missing TASK: ' + taskId, 2);
  return task;
}

function batches(tasks) {
  const ids = new Set(tasks.map(task => task.id));
  const pending = new Set(tasks.filter(task => task.status !== 'done').map(task => task.id));
  const finished = new Set(tasks.filter(task => task.status === 'done').map(task => task.id));
  const deps = Object.fromEntries(tasks.map(task => [task.id, new Set(task.depends)]));
  for (const task of tasks) {
    for (const dep of task.depends) f.demand(ids.has(dep), 'task_depends', task.id + ' depends on missing ' + dep);
  }
  const result = [];
  while (pending.size) {
    const ready = [...pending].filter(id => [...deps[id]].every(dep => finished.has(dep))).sort();
    f.demand(ready.length > 0, 'task_cycle', 'Dependency cycle among: ' + [...pending].sort().join(', '));
    result.push(ready);
    ready.forEach(id => { pending.delete(id); finished.add(id); });
  }
  return result;
}

function fieldLine(name, value) {
  return '- **' + name + '**:' + (value ? ' ' + value : '');
}

function setField(section, name, value) {
  const key = Object.keys(FIELDS).find(item => FIELDS[item] === name);
  const line = fieldLine(key, value);
  const pattern = new RegExp('^- \\*\\*' + key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\*\\*:[^\\n]*$', 'm');
  if (pattern.test(section)) return section.replace(pattern, () => line);
  const firstBreak = section.indexOf('\n');
  return firstBreak < 0 ? section + '\n' + line : section.slice(0, firstBreak + 1) + line + '\n' + section.slice(firstBreak + 1);
}

function appendSubsection(section, name, lines) {
  const marker = '### ' + name;
  const start = section.indexOf(marker);
  const addition = lines.join('\n') + '\n';
  if (start < 0) return section.replace(/\s*$/, '') + '\n\n' + marker + '\n\n' + addition;
  const rest = section.slice(start + marker.length);
  const next = /\r?\n###[ \t]/.exec(rest);
  const end = next ? start + marker.length + next.index : section.length;
  return section.slice(0, end).replace(/\s*$/, '') + '\n' + addition + section.slice(end);
}

function replaceTask(document, taskId, updater) {
  const task = find(document, taskId);
  const sections = splitSections(document.body).sections;
  const section = sections.find(item => item.id === taskId);
  f.demand(section, 'task_missing', 'Missing TASK: ' + taskId, 2);
  const updated = updater(section.text);
  const body = document.body.slice(0, section.start) + updated +
    document.body.slice(section.start + section.text.length);
  return { ...document, body, tasks: document.tasks.map(item => item.id === taskId ? { ...item, text: updated } : item) };
}

function updateTask(document, taskId, { status, field, value, log, verification } = {}) {
  return replaceTask(document, taskId, section => {
    let text = section;
    if (status) text = setField(text, 'status', status);
    if (field) text = setField(text, field, value);
    if (log) text = appendSubsection(text, 'Log', ['- [' + new Date().toISOString() + '] ' + log]);
    if (verification) text = appendSubsection(text, 'Verification', verification);
    return text;
  });
}

function write(document, body = document.body) {
  return fm.stringify(document, document.meta, body);
}

module.exports = {
  STATES, batches, find, parse, taskFrom, updateTask, validateSet, validateTask, validateTests, write
};
