'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const glob = require('./glob');

function defaults() {
  return { version: 1, workflow: 'hook', always: [], paths: {},
    budget: { maxTokens: 2500, maxBytes: 16384 },
    tests: { timeoutSeconds: 120, jobs: 2, regression: null },
    capture: { enabled: false, path: '.code-flow/process' } };
}
function reference(value) {
  f.string(value, 'Spec reference');
  const parts = value.split('#');
  f.demand(parts.length <= 2 && /^[a-z0-9][a-z0-9/_-]*$/.test(parts[0]) &&
    parts[0].split('/').every(Boolean) && (!parts[1] || /^RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(parts[1])) &&
    (parts.length === 1 || Boolean(parts[1])), 'invalid_reference', 'Invalid Spec reference: ' + value);
  return { id: parts[0], rule: parts[1] || null };
}
function validate(raw) {
  f.object(raw, 'config');
  f.demand(raw.version === 1, 'invalid_config', 'config.version must be 1');
  const base = defaults();
  const result = { ...raw, workflow: raw.workflow ?? base.workflow,
    always: raw.always ?? [], paths: raw.paths ?? {},
    budget: { ...base.budget, ...f.object(raw.budget ?? {}, 'budget') },
    tests: { ...base.tests, ...f.object(raw.tests ?? {}, 'tests') },
    capture: { ...base.capture, ...f.object(raw.capture ?? {}, 'capture') } };
  f.demand(['hook', 'full'].includes(result.workflow), 'invalid_config',
    'workflow must be hook or full');
  f.demand(typeof result.capture.enabled === 'boolean', 'invalid_config',
    'capture.enabled must be boolean');
  f.string(result.capture.path, 'capture.path');
  f.demand(/^\.code-flow\/[A-Za-z0-9._/-]+$/.test(result.capture.path) &&
    !result.capture.path.split('/').includes('..') && !result.capture.path.endsWith('/'),
    'invalid_config', 'capture.path must be a relative path under .code-flow');
  f.strings(result.always, 'always').forEach(reference);
  f.object(result.paths, 'paths');
  for (const [pattern, refs] of Object.entries(result.paths)) {
    glob.compile(pattern); f.strings(refs, 'paths references').forEach(reference);
  }
  f.positive(result.budget.maxTokens, 'maxTokens', true);
  f.positive(result.budget.maxBytes, 'maxBytes', true);
  f.positive(result.tests.timeoutSeconds, 'timeoutSeconds');
  f.positive(result.tests.jobs, 'jobs', true);
  if (result.tests.regression !== null) result.tests.regression = regression(result.tests.regression);
  return result;
}

function regression(value) {
  f.object(value, 'tests.regression');
  f.demand((value.argv !== undefined) !== (value.run !== undefined), 'invalid_config',
    'tests.regression requires exactly one of argv or run');
  if (value.argv !== undefined) f.strings(value.argv, 'tests.regression argv');
  else f.string(value.run, 'tests.regression run');
  if (value.cwd !== undefined) f.string(value.cwd, 'tests.regression cwd');
  if (value.timeout !== undefined) f.positive(value.timeout, 'tests.regression timeout');
  if (value.parallel !== undefined) f.demand(typeof value.parallel === 'boolean',
    'invalid_config', 'tests.regression parallel must be boolean');
  if (value.group !== undefined) f.string(value.group, 'tests.regression group');
  if (value.env !== undefined) f.object(value.env, 'tests.regression env');
  return { ...value, id: 'regression' };
}
function findRoot(cwd, required = true) {
  let current = f.realpath(cwd);
  while (true) {
    if (fs.existsSync(path.join(current, '.code-flow/config.json'))) return current;
    const parent = path.dirname(current);
    if (parent === current || fs.existsSync(path.join(current, '.git'))) break;
    current = parent;
  }
  f.demand(!required, 'project_missing', 'Run inside a project with .code-flow/config.json');
  return null;
}
function load(root) {
  const raw = f.readText(f.inside(root, '.code-flow/config.json'), 65536);
  f.demand(raw !== null, 'config_missing', 'Missing config.json');
  let data;
  try { data = JSON.parse(raw); } catch (error) {
    throw new f.FlowError('config_invalid', 'Invalid config JSON: ' + error.message);
  }
  return validate(data);
}
module.exports = { defaults, reference, validate, findRoot, load };
