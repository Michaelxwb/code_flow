'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

class FlowError extends Error {
  constructor(code, message, exitCode = 2) {
    super(message); this.name = 'FlowError'; this.code = code; this.exitCode = exitCode;
  }
}
function demand(condition, code, message, exitCode = 2) {
  if (!condition) throw new FlowError(code, message, exitCode);
}
function object(value, label) {
  demand(value !== null && typeof value === 'object' && !Array.isArray(value),
    'invalid_data', label + ' must be an object');
  return value;
}
function string(value, label) {
  demand(typeof value === 'string' && value.trim().length > 0 && !value.includes('\0'),
    'invalid_data', label + ' must be a nonempty string');
  return value;
}
function strings(value, label) {
  demand(Array.isArray(value), 'invalid_data', label + ' must be an array');
  return value.map(item => string(item, label));
}
function positive(value, label, integer = false) {
  demand(typeof value === 'number' && Number.isFinite(value) && value > 0 &&
    (!integer || Number.isSafeInteger(value)), 'invalid_data', label + ' must be positive' + (integer ? ' integer' : ''));
  return value;
}
function hash(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function readText(file, maximum = 4 * 1024 * 1024) {
  try {
    demand(fs.statSync(file).size <= maximum, 'file_too_large', 'File too large: ' + file);
    return fs.readFileSync(file, 'utf8');
  } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
function within(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function inside(root, relative) {
  string(relative, 'path');
  const clean = relative.replace(/\\/g, '/');
  demand(!path.posix.isAbsolute(clean) && !path.win32.isAbsolute(relative) &&
    !clean.split('/').includes('..') && !/[\r\n]/.test(clean), 'invalid_path', 'Invalid path: ' + relative);
  const base = fs.realpathSync(root);
  let current = base;
  for (const part of clean.split('/').filter(p => p && p !== '.')) {
    const next = path.join(current, part);
    if (!fs.existsSync(next) && fs.existsSync(current) && fs.statSync(current).isDirectory()) {
      const entries = fs.readdirSync(current);
      demand(!entries.some(name => name !== part && name.toLowerCase() === part.toLowerCase()) ||
        entries.includes(part), 'invalid_path', 'Path case mismatch: ' + relative);
    }
    current = next;
    if (fs.existsSync(current)) {
      const real = fs.realpathSync.native(current);
      demand(real === current || real.toLowerCase() !== current.toLowerCase(),
        'invalid_path', 'Path case mismatch: ' + relative);
      demand(within(base, real), 'invalid_path', 'Path escapes workspace: ' + relative);
    }
  }
  demand(within(base, current), 'invalid_path', 'Path escapes workspace: ' + relative);
  return current;
}
function removeIfPresent(file) {
  try { fs.unlinkSync(file); } catch (error) { if (error.code !== 'ENOENT') throw error; }
}
function atomicWrite(file, text, before = undefined) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = path.join(path.dirname(file), '.' + path.basename(file) + '.' + crypto.randomUUID() + '.tmp');
  let fd;
  try {
    fd = fs.openSync(temporary, 'wx', 0o600);
    fs.writeFileSync(fd, text, 'utf8'); fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined;
    demand(before === undefined || readText(file) === before, 'concurrent_change', 'Concurrent edit: ' + file, 1);
    fs.renameSync(temporary, file);
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    removeIfPresent(temporary);
  }
}
function transientRoot(root) {
  return path.join(os.tmpdir(), 'code-flow', hash(fs.realpathSync(root)));
}
function lockDirectory(root) {
  return path.join(transientRoot(root), 'locks');
}
function acquireIn(directory, key) {
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, hash(key) + '.lock');
  const owner = crypto.randomUUID();
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const fd = fs.openSync(file, 'wx', 0o600);
      try { fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, owner })); } finally { fs.closeSync(fd); }
      return { file, owner, key };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const raw = readText(file);
      if (raw === null) continue;
      let record;
      try { record = JSON.parse(raw); } catch (failure) {
        throw new FlowError('lock_invalid', 'Invalid lock JSON: ' + failure.message, 1);
      }
      demand(Number.isInteger(record.pid) && record.pid > 0, 'lock_invalid', 'Invalid lock owner: ' + file, 1);
      try { process.kill(record.pid, 0); } catch (failure) {
        if (failure.code === 'ESRCH' && readText(file) === raw) { removeIfPresent(file); continue; }
        if (failure.code !== 'EPERM') throw failure;
      }
      throw new FlowError('locked', 'Resource lock is held: ' + key, 1);
    }
  }
  throw new FlowError('locked', 'Cannot acquire lock: ' + key, 1);
}
function acquire(root, key) {
  return acquireIn(lockDirectory(root), key);
}
function releaseLock(lock) {
  const raw = readText(lock.file);
  if (raw === null) return;
  demand(JSON.parse(raw).owner === lock.owner, 'lock_changed', 'Lock ownership changed', 1);
  removeIfPresent(lock.file);
}
async function withLockIn(directory, key, operation) {
  const lock = acquireIn(directory, key);
  try { return await operation(); } finally { releaseLock(lock); }
}
async function withLock(root, key, operation) {
  return withLockIn(lockDirectory(root), key, operation);
}
module.exports = { FlowError, demand, object, string, strings, positive, hash,
  readText, within, inside, removeIfPresent, atomicWrite, transientRoot,
  acquireIn, releaseLock, withLockIn, withLock };
