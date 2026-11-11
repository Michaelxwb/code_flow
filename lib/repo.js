'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const f = require('./fs');

function run(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 1024 * 1024 });
  if (result.error) {
    throw new f.FlowError('git_identity', 'Cannot read Git identity: ' + result.error.message, 2);
  }
  f.demand(result.status === 0, 'git_identity',
    'Cannot read Git identity: ' + (result.stderr || 'git exited ' + result.status).trim(), 2);
  return result.stdout.trim();
}

function identity(root) {
  const real = f.realpath(root);
  if (!fs.existsSync(path.join(real, '.git'))) return { git: false, root: real, linked: false };
  const gitDir = path.resolve(real, run(real, ['rev-parse', '--git-dir']));
  const commonDir = path.resolve(real, run(real, ['rev-parse', '--git-common-dir']));
  const top = f.realpath(run(real, ['rev-parse', '--show-toplevel']));
  const linked = f.realpath(gitDir) !== f.realpath(commonDir);
  const branchResult = spawnSync('git', ['symbolic-ref', '-q', 'HEAD'], { cwd: real, encoding: 'utf8' });
  return { git: true, root: real, top, git_dir: f.realpath(gitDir),
    git_common_dir: f.realpath(commonDir), branch: branchResult.status === 0 ? branchResult.stdout.trim() : null,
    linked };
}

function requireCoordinator(root, operation) {
  const current = identity(root);
  f.demand(!current.linked, 'coordinator_required',
    operation + ' must run in the coordinator worktree: ' + current.top, 1);
  return current;
}

module.exports = { identity, requireCoordinator };
