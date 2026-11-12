'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const workspace = process.env.EVAL_WORKSPACE;
const fixture = process.env.EVAL_FIXTURE;
const mode = process.env.EVAL_PATH;
const root = path.resolve(__dirname, 'fixtures', fixture);
fs.cpSync(path.join(root, 'solution'), workspace, { recursive: true, force: true });
if (mode === 'minimal') process.exit(0);

const tests = { 'unique-words': 'test/words.test.js', 'csv-line': 'test/csv.test.js',
  'rate-limit': 'test/limiter.test.js', 'event-bus': 'test/bus.test.js',
  pagination: 'test/paginate.test.js', 'retry-spec': 'test/retry.test.js',
  'retry-batch': ['test/retry.test.js', 'test/batch.test.js'],
  'cancel-order': 'test/orders.test.js' };
const metaFile = path.join(root, 'fixture.json');
const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
const taskTests = Array.isArray(tests[fixture]) ? tests[fixture] : [tests[fixture]];
const count = meta.tasks ?? taskTests.length;
const relative = `.code-flow/tasks/2026-11-12/${fixture}/${fixture}.md`;
const directory = path.dirname(path.join(workspace, relative));
fs.mkdirSync(directory, { recursive: true });
if (mode === 'full') {
  for (const suffix of ['prd', 'design', 'scenarios']) {
    fs.writeFileSync(path.join(directory, `${fixture}.${suffix}.md`), `# ${fixture} ${suffix}\n`);
  }
}
const sections = [];
for (let index = 0; index < count; index++) {
  const id = 'TASK-' + String(index + 1).padStart(3, '0');
  const depends = index === 0 ? '' : 'TASK-' + String(index).padStart(3, '0');
  const test = taskTests[index] ?? taskTests[0];
  const testsJson = JSON.stringify([{ id: 'visible', argv: ['node', '--test', test] }], null, 2);
  sections.push(`## ${id}: Implement\n\n- **Status**: draft\n- **Depends**: ${depends}\n` +
    `- **Spec-Refs**: shared/base\n\n### Tests\n\n\`\`\`json\n${testsJson}\n\`\`\`\n\n` +
    `### Spec Delta\n\n\`\`\`json\n[]\n\`\`\`\n`);
}
fs.writeFileSync(path.join(workspace, relative),
  `---\n{"version":1,"requirement":"${fixture}"}\n---\n# Tasks: ${fixture}\n\n` + sections.join('\n'));

function cli(args) {
  const result = spawnSync('code-flow', args, { cwd: workspace, env: process.env, encoding: 'utf8' });
  if (result.status !== 0) {
    process.stderr.write((result.stdout || '') + (result.stderr || ''));
    process.exit(result.status ?? 1);
  }
  return result.stdout;
}
for (let index = 0; index < count; index++) {
  const id = 'TASK-' + String(index + 1).padStart(3, '0');
  cli(['task', 'start', relative, '--task', id]);
  cli(['task', 'finish', relative, '--task', id]);
}
