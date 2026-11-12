'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const fm = require('./frontmatter');
const { reference } = require('./config');
const markdown = require('./markdown');

function parseRules(body) {
  const lines = body.replace(/\r\n/g, '\n').split('\n');
  const rules = [], used = new Set();
  let section = false, fence = null, current = null;
  const finish = end => {
    if (!current) return;
    current.end = end;
    current.text = lines.slice(current.start, end).map((line, i) =>
      i === 0 ? line.replace(/^- \[RULE-[^\]]+\] /, '') : line.replace(/^  /, '')).join('\n').trim();
    f.demand(!used.has(current.id), 'duplicate_rule', 'Duplicate Rule ID: ' + current.id);
    used.add(current.id);
    rules.push(current); current = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i], marker = markdown.fenceMarker(line, fence);
    if (marker) {
      fence = marker.next;
      continue;
    }
    if (fence) continue;
    if (/^##\s/.test(line)) { finish(i); section = /^## Rules\s*$/.test(line); continue; }
    if (!section) continue;
    const match = line.match(/^- \[(RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\] (.+)$/);
    if (match) { finish(i); current = { id: match[1], start: i }; }
    else if (/^- /.test(line)) {
      finish(i);
      throw new f.FlowError('rule_invalid', 'Rule must have a stable RULE ID: ' + line);
    }
  }
  f.demand(!fence, 'rule_fence', 'Unclosed code fence in Spec');
  finish(lines.length);
  return { rules, lines };
}
function header(meta) {
  f.string(meta.description, 'Spec description');
  f.positive(meta.next_rule, 'Spec next_rule', true);
  return meta;
}
function load(root, id) {
  f.demand(!id.includes('#'), 'invalid_reference', 'Expected Spec path without Rule suffix');
  reference(id);
  const file = f.inside(root, '.code-flow/specs/' + id + '.md');
  const raw = f.readText(file);
  f.demand(raw !== null, 'spec_missing', 'Missing Spec: ' + id);
  const document = fm.parse(raw);
  header(document.meta);
  return { ...document, ...parseRules(document.body), id, file };
}
function walk(directory, prefix = '') {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
    .flatMap(entry => {
      const relative = prefix + entry.name;
      if (entry.isSymbolicLink()) return [];
      if (entry.isDirectory()) return walk(path.join(directory, entry.name), relative + '/');
      return entry.isFile() && entry.name.endsWith('.md') ? [relative] : [];
    });
}
function list(root, full = true) {
  const items = [], diagnostics = [];
  for (const relative of walk(f.inside(root, '.code-flow/specs'))) {
    const id = relative.slice(0, -3);
    try {
      reference(id);
      const info = full ? load(root, id) : { meta: header(fm.readHeader(f.inside(root, '.code-flow/specs/' + relative))) };
      items.push({ id, path: '.code-flow/specs/' + relative, description: info.meta.description,
        ...(full ? { rules: info.rules.length } : {}) });
    } catch (error) { diagnostics.push({ code: error.code || 'spec_error', source: id, message: error.message }); }
  }
  return { items, diagnostics };
}
module.exports = { load, list, parseRules, walk, header };
