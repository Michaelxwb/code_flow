'use strict';
const path = require('node:path');
const f = require('./fs');
const fm = require('./frontmatter');
const config = require('./config');
const glob = require('./glob');
const markdown = require('./markdown');

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
    const marker = markdown.fenceMarker(line, fence);
    if (marker) {
      fence = marker.next;
    } else if (!fence && /^##[ \t]/.test(line)) {
      const parsed = heading(line);
      if (parsed) headings.push({ ...parsed, start: offset });
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

function fieldEntries(text) {
  const values = new Map();
  let fence = null, offset = 0;
  for (const line of text.split('\n')) {
    const start = offset;
    offset += line.length + 1;
    const marker = markdown.fenceMarker(line, fence);
    if (marker) {
      fence = marker.next;
      continue;
    }
    if (fence) continue;
    const match = /^- \*\*([^*]+)\*\*:[ \t]*(.*)$/.exec(line.replace(/\r$/, ''));
    if (match && Object.hasOwn(FIELDS, match[1])) {
      const name = FIELDS[match[1]];
      f.demand(!values.has(name), 'task_field_duplicate', 'Duplicate Task field: ' + match[1]);
      values.set(name, { value: match[2].trim(), start, end: start + line.length });
    }
  }
  return values;
}

function fieldMap(text) {
  return Object.fromEntries([...fieldEntries(text)].map(([name, item]) => [name, item.value]));
}

function subsectionRange(text, name) {
  let area = null, fence = null, offset = 0;
  for (const line of text.split('\n')) {
    const start = offset;
    offset += line.length + 1;
    const marker = markdown.fenceMarker(line, fence);
    if (marker) {
      fence = marker.next;
      continue;
    }
    if (fence) continue;
    if (area && /^###[ \t]/.test(line)) return { ...area, end: start };
    if (line.replace(/\r$/, '') === '### ' + name) {
      area = { start, contentStart: Math.min(offset, text.length) };
    }
  }
  return area ? { ...area, end: text.length } : null;
}

function subsection(text, name) {
  const area = subsectionRange(text, name);
  return area ? text.slice(area.contentStart, area.end) : null;
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

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

function testsDigest(task) {
  return f.hash(JSON.stringify(canonical(task.tests))).slice(0, 12);
}

function startedTests(text) {
  const matches = [...String(text).matchAll(/^-[ \t]+\[[^\]]+\][ \t]+started[ \t]+tests=([a-f0-9]{12})/gm)];
  return matches.length ? matches.at(-1)[1] : null;
}

function validateTests(tests) {
  f.demand(Array.isArray(tests), 'task_tests', 'Task tests must be an array');
  const ids = new Set();
  for (const test of tests) {
    f.object(test, 'test'); f.string(test.id, 'test.id');
    f.demand(!/[\r\n]/.test(test.id), 'test_id', 'test.id must fit on one line');
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
  f.demand(STATES.includes(task.status), 'task_status', task.id + ': invalid Status: ' + task.status);
  for (const dep of task.depends) f.demand(/^TASK-\d+$/.test(dep) && dep !== task.id,
    'task_depends', 'Invalid dependency for ' + task.id + ': ' + dep);
  task.scenarios.forEach(id => f.demand(id.length <= 120 && !/[\r\n]/.test(id),
    'task_scenario', 'Invalid scenario reference: ' + id));
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
  f.demand(values.status !== undefined && values.status !== '', 'task_status',
    section.id + ': missing Status field');
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
  const field = fieldEntries(section).get(name);
  if (field) return section.slice(0, field.start) + line + section.slice(field.end);
  const firstBreak = section.indexOf('\n');
  return firstBreak < 0 ? section + '\n' + line : section.slice(0, firstBreak + 1) + line + '\n' + section.slice(firstBreak + 1);
}

function appendSubsection(section, name, lines) {
  const marker = '### ' + name;
  const area = subsectionRange(section, name);
  const addition = lines.join('\n') + '\n';
  if (!area) return section.replace(/\s*$/, '') + '\n\n' + marker + '\n\n' + addition;
  return section.slice(0, area.end).replace(/\s*$/, '') + '\n' + addition +
    (area.end < section.length ? '\n' : '') + section.slice(area.end);
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

function checkChecklist(section) {
  const area = subsectionRange(section, 'Checklist');
  if (!area) return section;
  const body = section.slice(area.contentStart, area.end)
    .replace(/^(\s*)- \[ \]/gm, '$1- [x]');
  return section.slice(0, area.contentStart) + body + section.slice(area.end);
}

function completeChecklists(document) {
  return document.tasks.reduce((current, task) => task.status === 'done'
    ? updateTask(current, task.id, { checklist: 'done' }) : current, document);
}

function updateTask(document, taskId, { status, field, value, log, verification, checklist } = {}) {
  return replaceTask(document, taskId, section => {
    let text = section;
    if (status) text = setField(text, 'status', status);
    if (field) text = setField(text, field, value);
    if (log) text = appendSubsection(text, 'Log', ['- [' + new Date().toISOString() + '] ' +
      log.replace(/[\r\n]+/g, ' ')]);
    if (verification) text = appendSubsection(text, 'Verification', verification);
    if (checklist === 'done') text = checkChecklist(text);
    return text;
  });
}

function write(document, body = document.body) {
  return fm.stringify(document, document.meta, body);
}

module.exports = {
  STATES, batches, find, parse, startedTests, taskFrom, testsDigest, updateTask, completeChecklists,
  validateSet, validateTask, validateTests, write
};
