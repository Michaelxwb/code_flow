'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const repo = require('./repo');

const bases = new Map();

function base(root) {
  const real = f.realpath(root);
  if (bases.has(real)) return bases.get(real);
  const identity = repo.identity(real);
  const value = identity.git ? identity.git_common_dir : real;
  bases.set(real, value);
  return value;
}

function directory(root) {
  return path.join(f.transientRoot(base(root)), 'locks');
}

function withRepository(root, operation) {
  return f.withLockIn(directory(root), 'repository', operation);
}

function withRepositorySync(root, operation) {
  const lock = f.acquireIn(directory(root), 'repository');
  try { return operation(); } finally { f.releaseLock(lock); }
}

function acquireGroup(root, group, timeoutSeconds, signal) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      if (signal.aborted) { reject(Object.assign(new Error('cancelled'), { code: 'cancelled' })); return; }
      try { resolve(f.acquireIn(directory(root), 'group:' + group)); return; } catch (error) {
        if (error.code !== 'locked') { reject(error); return; }
      }
      if (Date.now() >= deadline) {
        reject(Object.assign(new Error('group lock timeout: ' + group), { code: 'lock_timeout' })); return;
      }
      setTimeout(attempt, 25);
    };
    attempt();
  });
}

function release(lock) {
  f.releaseLock(lock);
}

module.exports = { base, directory, withRepository, withRepositorySync, acquireGroup, release };
