'use strict';
const path = require('node:path');
const fs = require('node:fs');
const f = require('./fs');
function token(root, platform, sessionId) {
  f.string(sessionId, 'session ID');
  return f.hash(JSON.stringify([f.realpath(root), platform, sessionId]));
}
function location(root, value) {
  f.demand(typeof value === 'string' && /^[a-f0-9]{64}$/.test(value),
    'session_invalid', 'Session token must be 64 lowercase hexadecimal characters');
  return path.join(f.transientRoot(root), 'sessions', value + '.json');
}
function read(root, value) {
  const raw = f.readText(location(root, value), 65536);
  if (raw === null) return null;
  let result;
  try { result = JSON.parse(raw); } catch (error) {
    throw new f.FlowError('session_invalid', 'Invalid session binding: ' + error.message);
  }
  f.object(result, 'session binding');
  f.string(result.task_file, 'session task_file');
  f.string(result.task_id, 'session task_id');
  return result;
}
async function bind(root, value, taskFile, taskId) {
  const file = location(root, value);
  f.string(taskFile, 'task file');
  f.string(taskId, 'task id');
  await f.withLock(root, 'session:' + value, async () => {
    f.atomicWrite(file, JSON.stringify({ task_file: taskFile, task_id: taskId,
      bound_at: new Date().toISOString() }) + '\n', f.readText(file));
  });
}
async function unbind(root, value) {
  const file = location(root, value);
  await f.withLock(root, 'session:' + value, async () => f.removeIfPresent(file));
  return { ok: true, action: 'unbind' };
}
module.exports = { token, location, read, bind, unbind };
