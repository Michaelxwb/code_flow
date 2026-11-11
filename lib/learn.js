'use strict';
const path = require('node:path');
const f = require('./fs');
const fm = require('./frontmatter');
const spec = require('./spec');
const { reference } = require('./config');
function normalize(text) { return text.replace(/\r\n/g, '\n').trim(); }
function validate(delta) {
  f.object(delta, 'Delta');
  f.demand(typeof delta.id === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(delta.id), 'delta_id', 'Invalid Delta ID');
  f.demand(['add', 'update', 'remove'].includes(delta.op), 'delta_op', 'Invalid Delta operation');
  const target = reference(delta.target);
  f.demand(!target.rule, 'delta_target', 'Delta target must be a Spec path');
  const result = { id: delta.id, op: delta.op, target: target.id,
    evidence: normalize(f.string(delta.evidence, 'Delta evidence')) };
  if (delta.op !== 'remove') result.rule = normalize(f.string(delta.rule, 'Delta rule'));
  if (delta.op !== 'add') {
    f.string(delta.ref, 'Delta ref');
    f.demand(/^RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(delta.ref), 'delta_ref', 'Invalid Delta Rule reference');
    result.ref = delta.ref; result.before = normalize(f.string(delta.before, 'Delta before'));
  }
  return result;
}
function deltas(task) {
  const source = task.specDelta ?? [];
  f.demand(Array.isArray(source), 'delta_invalid', 'Spec Delta must be an array');
  const ids = new Set();
  return source.map(item => {
    const delta = validate(item);
    f.demand(!ids.has(delta.id), 'delta_duplicate', 'Duplicate Delta ID: ' + delta.id); ids.add(delta.id);
    return delta;
  });
}
function section(body, name) {
  const lines = body.replace(/\r\n/g, '\n').split('\n');
  let start = -1, fence = null;
  for (let i = 0; i < lines.length; i++) {
    const marker = lines[i].match(/^\s*(`{3,}|~{3,})/);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      continue;
    }
    if (fence) continue;
    if (lines[i] === '## ' + name && start === -1) { start = i; continue; }
    if (start !== -1 && /^## /.test(lines[i])) return { lines, start, end: i };
  }
  return { lines, start, end: lines.length };
}
function records(body) {
  const area = section(body, 'Applied Deltas');
  if (area.start < 0) return [];
  return area.lines.slice(area.start + 1, area.end).filter(line => line.startsWith('- ')).map(line => {
    let record;
    try { record = JSON.parse(line.slice(2)); } catch (error) {
      throw new f.FlowError('delta_history', 'Invalid Applied Deltas JSON: ' + error.message);
    }
    f.object(record, 'Applied Delta');
    f.string(record.source, 'Applied Delta source');
    f.demand(/^RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(record.rule) &&
      /^[a-f0-9]{64}$/.test(record.payload_sha256), 'delta_history', 'Invalid Applied Delta record');
    return record;
  });
}
function appendSection(body, name, addition) {
  const area = section(body, name), lines = area.lines;
  if (area.start < 0) return body.replace(/\s*$/, '') + '\n\n## ' + name + '\n\n' + addition + '\n';
  lines.splice(area.end, 0, addition, '');
  return lines.join('\n');
}
function ruleBlock(id, text) {
  return normalize(text).split('\n').map((line, index) => index ? (line ? '  ' + line : '') : '- [' + id + '] ' + line).join('\n');
}
function mutate(document, delta, history) {
  const parsed = spec.parseRules(document.body), meta = { ...document.meta };
  const existing = parsed.rules.find(rule => rule.id === delta.ref);
  if (delta.op !== 'add') {
    f.demand(existing && normalize(existing.text) === delta.before, 'delta_precondition',
      'Rule changed or missing: ' + delta.target + '#' + delta.ref, 1);
    const lines = parsed.lines;
    lines.splice(existing.start, existing.end - existing.start,
      ...(delta.op === 'remove' ? [] : [ruleBlock(existing.id, delta.rule), '']));
    return { body: lines.join('\n'), meta, rule: existing.id, status: 'applied' };
  }
  const duplicate = parsed.rules.find(rule => normalize(rule.text) === delta.rule);
  if (duplicate) return { body: document.body, meta, rule: duplicate.id, status: 'duplicate' };
  const used = [...parsed.rules.map(rule => rule.id), ...history.map(item => item.rule)];
  f.demand(!used.some(id => /^RULE-\d+$/.test(id) && Number(id.slice(5)) >= meta.next_rule),
    'rule_counter', 'next_rule would reuse an allocated Rule ID', 1);
  f.demand(Number.isSafeInteger(meta.next_rule + 1), 'rule_counter', 'next_rule exhausted', 1);
  const id = 'RULE-' + String(meta.next_rule).padStart(3, '0'); meta.next_rule++;
  return { body: appendSection(document.body, 'Rules', ruleBlock(id, delta.rule)), meta, rule: id, status: 'applied' };
}
function applyDelta(document, delta, source, globalHistory) {
  const targetHistory = records(document.body);
  const payload = f.hash(JSON.stringify(delta));
  const previous = globalHistory.get(source) ?? [];
  f.demand(previous.length <= 1, 'delta_history', 'Duplicate Applied Delta identity: ' + source, 1);
  if (previous.length) {
    f.demand(previous[0].record.payload_sha256 === payload, 'delta_conflict',
      'Applied Delta payload changed: ' + source, 1);
    return { document, result: { source, target: delta.target, rule: previous[0].record.rule,
      status: 'already-applied' } };
  }
  const mutation = mutate({ ...document, body: document.body.replace(/\r\n/g, '\n') }, delta, targetHistory);
  const record = { source, op: delta.op, rule: mutation.rule, payload_sha256: payload, at: new Date().toISOString() };
  globalHistory.set(source, [{ record, target: document.id }]);
  const body = appendSection(mutation.body, 'Applied Deltas', '- ' + JSON.stringify(record));
  const after = fm.stringify(document, mutation.meta, body.replace(/\n/g, document.eol));
  const updated = { ...fm.parse(after), id: document.id, file: document.file };
  return { document: updated, result: { source, target: delta.target, rule: mutation.rule, status: mutation.status } };
}

function loadHistory(root) {
  const base = path.join(root, '.code-flow/specs'), history = new Map();
  for (const relative of spec.walk(base)) {
    const id = relative.slice(0, -3), document = spec.load(root, id);
    for (const record of records(document.body)) {
      const list = history.get(record.source) ?? [];
      list.push({ record, target: id });
      history.set(record.source, list);
    }
  }
  return history;
}
function plan(root, tasks) {
  const changes = new Map(), results = [], sources = new Map(), history = loadHistory(root);
  const ordered = [...tasks].sort((a, b) =>
    a.relative.localeCompare(b.relative) || a.id.localeCompare(b.id));
  for (const task of ordered) {
    f.demand(task.status === 'done' && !task.relative.startsWith('.code-flow/tasks/archived/'),
      'learn_state', 'Learning requires an unarchived done Task', 1);
    sources.set(task.relative, { file: task.document.file, raw: task.document.raw });
    for (const delta of deltas(task)) {
      if (!changes.has(delta.target)) {
        const loaded = spec.load(root, delta.target);
        changes.set(delta.target, { before: loaded.raw, document: loaded });
      }
      const item = changes.get(delta.target);
      const source = task.relative.slice('.code-flow/tasks/'.length) + '#' + task.id + '#' + delta.id;
      const applied = applyDelta(item.document, delta, source, history);
      item.document = applied.document; results.push(applied.result);
    }
  }
  return { changes: [...changes.values()].sort((a, b) => a.document.id.localeCompare(b.document.id)), results,
    sources: [...sources.values()] };
}
function checkSources(prepared) {
  for (const item of prepared.sources) f.demand(f.readText(item.file) === item.raw,
    'concurrent_change', 'Task changed during learning: ' + item.file, 1);
}
function commit(prepared, writer = f.atomicWrite) {
  checkSources(prepared);
  for (const item of prepared.changes) {
    checkSources(prepared);
    if (item.document.raw !== item.before) writer(item.document.file, item.document.raw, item.before);
  }
  return { ok: true, action: 'learn', results: prepared.results };
}
function preview(prepared) {
  return { ok: true, action: 'learn', dry_run: true, results: prepared.results,
    changes: prepared.changes.filter(item => item.before !== item.document.raw)
      .map(item => ({ file: item.document.file, before: item.before, after: item.document.raw })) };
}
async function apply(root, documents, dryRun = false) {
  if (dryRun) return preview(plan(root, documents));
  return f.withLock(root, 'write', async () => commit(plan(root, documents)));
}
module.exports = { validate, deltas, plan, commit, preview, apply, records, normalize };
