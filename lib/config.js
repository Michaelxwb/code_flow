'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const glob = require('./glob');

function defaults() {
  return { version: 1, always: [], paths: {}, budget: { maxTokens: 2500, maxBytes: 16384 },
    tests: { timeoutSeconds: 120, jobs: 2 } };
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
  const result = { ...raw, always: raw.always ?? [], paths: raw.paths ?? {},
    budget: { ...base.budget, ...f.object(raw.budget ?? {}, 'budget') },
    tests: { ...base.tests, ...f.object(raw.tests ?? {}, 'tests') } };
  f.strings(result.always, 'always').forEach(reference);
  f.object(result.paths, 'paths');
  for (const [pattern, refs] of Object.entries(result.paths)) {
    glob.compile(pattern); f.strings(refs, 'paths references').forEach(reference);
  }
  f.positive(result.budget.maxTokens, 'maxTokens', true);
  f.positive(result.budget.maxBytes, 'maxBytes', true);
  f.positive(result.tests.timeoutSeconds, 'timeoutSeconds');
  f.positive(result.tests.jobs, 'jobs', true);
  return result;
}
function findRoot(cwd, required = true) {
  let current = fs.realpathSync(cwd);
  while (true) {
    if (fs.existsSync(path.join(current, '.code-flow/config.json'))) return current;
    const parent = path.dirname(current);
    if (parent === current) break;
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
