'use strict';
const path = require('node:path');
const f = require('./fs');
const config = require('./config');
const spec = require('./spec');
const glob = require('./glob');
function diagnostic(error, source) {
  return { code: error.code || 'read_error', source, message: error.message };
}
function requests(settings, task, paths) {
  const result = settings.always.map(ref => ({ ref, priority: 0, source: 'always' }));
  for (const ref of task?.specRefs ?? []) result.push({ ref, priority: ref.includes('#') ? 1 : 2, source: 'task.spec_refs' });
  for (const file of paths) {
    for (const [pattern, refs] of Object.entries(settings.paths)) {
      if (glob.matches(pattern, file)) {
        for (const ref of refs) result.push({ ref, priority: 3, source: 'path:' + file });
      }
    }
  }
  return result.sort((a, b) => a.priority - b.priority);
}
function select(root, entries, diagnostics) {
  const loaded = new Map(), selected = new Map();
  for (const entry of entries) {
    try {
      const ref = config.reference(entry.ref);
      if (!loaded.has(ref.id)) loaded.set(ref.id, spec.load(root, ref.id));
      const document = loaded.get(ref.id);
      const rules = ref.rule ? document.rules.filter(rule => rule.id === ref.rule) : document.rules;
      f.demand(!ref.rule || rules.length, 'rule_missing', 'Missing Rule: ' + entry.ref);
      for (const rule of rules) {
        const key = ref.id + '#' + rule.id;
        if (!selected.has(key)) selected.set(key, { ref: key, spec: ref.id, rule: rule.id,
          text: rule.text, source: '.code-flow/specs/' + ref.id + '.md', selectedBy: [] });
        const item = selected.get(key);
        if (!item.selectedBy.includes(entry.source)) item.selectedBy.push(entry.source);
      }
    } catch (error) { diagnostics.push(diagnostic(error, entry.ref)); }
  }
  return [...selected.values()];
}
function estimate(text) {
  const ascii = (text.match(/[\x00-\x7f]/g) || []).length;
  return Math.ceil(ascii / 4) + [...text].length - ascii;
}
function ruleText(rule, previous) {
  const header = !previous || previous.spec !== rule.spec || previous.source !== rule.source ||
    previous.selectedBy.join(', ') !== rule.selectedBy.join(', ')
    ? '### ' + rule.spec + '\nsource: ' + rule.source +
      '\nselected-by: ' + rule.selectedBy.join(', ') + '\n'
    : '';
  return header + '\n- [' + rule.rule + '] ' + rule.text + '\n';
}
function fits(text, budget) {
  return estimate(text) <= budget.maxTokens && Buffer.byteLength(text, 'utf8') <= budget.maxBytes;
}
function render(selected, settings, context) {
  const heading = '## Spec Constraints (latest)\n\n' +
    (context.session ? 'session: ' + context.session + '\n' : '') +
    (context.task ? 'task: ' + context.task + '\n' : '') +
    'workflow: ' + settings.workflow + '\n';
  const readMore = '\nread-more: code-flow spec inject' +
    (context.taskFile && context.taskId ? ' --task-file "' + context.taskFile + '" --task ' + context.taskId : '') +
    ' --full\n';
  const reserve = '\nomitted: ' + selected.slice(0, 3).map(item => item.ref).join(', ') + readMore;
  const emitted = [], omitted = [];
  let text = heading, last = null;
  for (const item of selected) {
    const addition = '\n' + ruleText(item, last);
    if (context.full || fits(text + addition + reserve, settings.budget)) {
      text += addition; emitted.push(item.ref); last = item;
    } else omitted.push(item);
  }
  if (omitted.length) text += '\nomitted: ' + omitted.slice(0, 3).map(item => item.ref).join(', ') +
    (omitted.length > 3 ? ' (+' + (omitted.length - 3) + ')' : '') + readMore;
  if (!context.full && !fits(text, settings.budget)) {
    text = 'Spec budget too small. Run code-flow spec inject --full.\n';
  }
  return { text, emitted, omitted: omitted.map(item => ({ ref: item.ref, source: item.source })) };
}
function normalizePaths(root, paths) {
  return [...new Set(paths.map(file => {
    const relative = path.isAbsolute(file) ? path.relative(root, file) : file;
    f.inside(root, relative);
    return relative.replace(/\\/g, '/').replace(/^\.\//, '');
  }))];
}
function inject(root, options = {}) {
  const settings = config.load(root), diagnostics = [];
  let task = null, requirement = null;
  if (options.requirementFile) {
    try { requirement = require('./task').loadRequirement(root, options.requirementFile); } catch (error) {
      diagnostics.push(diagnostic(error, options.requirementFile));
    }
  } else if (options.taskFile) {
    try { task = require('./task').loadTask(root, options.taskFile, options.taskId); } catch (error) {
      if (options.strictTask) throw error;
      diagnostics.push(diagnostic(error, options.taskFile));
    }
  }
  const paths = [];
  for (const file of options.paths ?? []) {
    try { paths.push(...normalizePaths(root, [file])); } catch (error) { diagnostics.push(diagnostic(error, file)); }
  }
  const entries = requests(settings, requirement ?? task, paths), selected = select(root, entries, diagnostics);
  let catalog = [];
  if (!task && entries.length === settings.always.length) {
    const listing = spec.list(root, false); catalog = listing.items; diagnostics.push(...listing.diagnostics);
  }
  const identity = requirement ? requirement.relative + '#REQUIREMENT' : task ? task.relative + '#' + task.id : null;
  const result = render(selected, settings, { ...options, task: identity,
    taskFile: requirement?.relative ?? task?.relative,
    taskId: requirement ? null : task?.id });
  if (catalog.length) {
    const navigation = '\n## Spec Catalog\n' + catalog.slice(0, 20).map(item => item.id + ': ' + item.description).join('\n') +
      '\n' + catalog.length + ' Specs; code-flow spec list --json\n';
    if (options.full || fits(result.text + navigation, settings.budget)) result.text += navigation;
  }
  return { ...result, selected, diagnostics, catalog, task: identity,
    taskFile: task?.relative ?? null, taskId: task?.id ?? null,
    session: options.session ?? null };
}
module.exports = { inject, select, requests, render, estimate, normalizePaths };
