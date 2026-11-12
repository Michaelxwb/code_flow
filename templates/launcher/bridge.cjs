'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');

const MAX_INPUT = 1024 * 1024;
const MAX_OUTPUT = 1024 * 1024;
const MAX_DIAGNOSTIC = 4096;
const PROBE_MS = 800;
const RUN_RESERVE_MS = 1200;
const CACHE_TTL_MS = 600000;
const TOTAL_MS = 2000;

function emptyPayload(format) {
  return format === 'opencode'
    ? { context: '' }
    : { hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: '' } };
}

function validPayload(format, payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  if (format === 'opencode') return typeof payload.context === 'string';
  const hook = payload.hookSpecificOutput;
  return hook !== null && typeof hook === 'object' &&
    hook.hookEventName === 'UserPromptSubmit' && typeof hook.additionalContext === 'string';
}

function normalizePayload(format, payload) {
  if (!validPayload(format, payload)) return null;
  return format === 'opencode' ? { context: payload.context } : {
    hookSpecificOutput: { hookEventName: 'UserPromptSubmit',
      additionalContext: payload.hookSpecificOutput.additionalContext }
  };
}

function emit(format, payload) {
  process.stdout.write(JSON.stringify(payload) + '\n');
}

function readStdin(deadline) {
  return new Promise(resolve => {
    const chunks = [];
    let size = 0, timer;
    const finish = value => {
      clearTimeout(timer);
      process.stdin.removeAllListeners();
      process.stdin.destroy();
      resolve(value);
    };
    timer = setTimeout(() => finish(''), Math.max(0, Math.min(TOTAL_MS, deadline - Date.now())));
    process.stdin.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_INPUT) finish('');
      else chunks.push(chunk);
    });
    process.stdin.on('end', () => finish(Buffer.concat(chunks).toString('utf8')));
    process.stdin.on('error', () => finish(''));
  });
}

function inside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..');
}

function safeCandidate(root, candidate) {
  try {
    const real = fs.realpathSync(candidate);
    return fs.statSync(real).isFile() && !inside(root, real);
  } catch (_) { return false; }
}

function realFile(candidate) {
  try { return fs.realpathSync(candidate); } catch (_) { return null; }
}

function findOnPath(root) {
  const names = process.platform === 'win32'
    ? ['code-flow.cmd', 'code-flow.exe', 'code-flow']
    : ['code-flow'];
  const found = [];
  for (const directory of (process.env.PATH || '').split(path.delimiter)) {
    if (!directory) continue;
    for (const name of names) {
      const candidate = path.join(directory, name);
      if (safeCandidate(root, candidate)) found.push(candidate);
    }
  }
  return [...new Set(found)];
}

function packageIdentity(entry) {
  let directory = path.dirname(entry);
  while (directory !== path.dirname(directory)) {
    const file = path.join(directory, 'package.json');
    if (fs.existsSync(file)) {
      try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return null; }
    }
    directory = path.dirname(directory);
  }
  return null;
}

function validCapability(data, candidate) {
  if (!data || data.package !== '@michaelxwb/code-flow' || data.hook_protocol !== 1) return false;
  if (typeof data.node !== 'string' || !path.isAbsolute(data.node)) return false;
  if (typeof data.entry !== 'string' || !path.isAbsolute(data.entry)) return false;
  const dataEntry = realFile(data.entry), candidateEntry = realFile(candidate);
  if (!dataEntry || !candidateEntry) return false;
  const shim = process.platform === 'win32' || !/\.js$/i.test(candidateEntry);
  if (candidateEntry !== dataEntry && !shim) return false;
  const pkg = packageIdentity(dataEntry);
  if (!pkg || pkg.name !== data.package || pkg.version !== data.version) return false;
  const bin = pkg.bin && typeof pkg.bin === 'object' ? pkg.bin['code-flow'] : pkg.bin;
  if (typeof bin !== 'string' ||
    path.resolve(path.dirname(dataEntry), '..', bin) !== path.resolve(dataEntry)) return false;
  return pkg.codeFlow && pkg.codeFlow.hookProtocol === 1;
}

function probeCommand(candidate, args) {
  if (process.platform === 'win32' && /\.(?:cmd|bat)$/i.test(candidate)) {
    const quote = value => '"' + value.replace(/"/g, '""') + '"';
    return [process.env.ComSpec || 'cmd.exe',
      ['/d', '/s', '/c', [candidate, ...args].map(quote).join(' ')]];
  }
  return [candidate, args];
}

function probe(root, candidate, budget) {
  const [file, args] = probeCommand(candidate, ['hook', 'capabilities', '--json']);
  return new Promise(resolve => {
    const chunks = [];
    let size = 0, settled = false, timer;
    const child = spawn(file, args, {
      cwd: root, stdio: ['ignore', 'pipe', 'pipe'], detached: process.platform !== 'win32',
      windowsHide: true
    });
    const finish = ok => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      try { child.stdout.destroy(); child.stderr.destroy(); } catch (_) { /* best effort */ }
      if (!ok) { resolve(null); return; }
      try {
        const data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        resolve(validCapability(data, candidate) ? data : null);
      } catch (_) { resolve(null); }
    };
    timer = setTimeout(() => { killTree(child); finish(false); }, Math.max(1, Math.min(PROBE_MS, budget)));
    child.on('error', () => finish(false));
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_OUTPUT) { killTree(child); finish(false); }
      else chunks.push(chunk);
    });
    child.stderr.on('data', () => {});
    child.on('close', code => finish(code === 0));
  });
}

function cacheFile(root) {
  const digest = crypto.createHash('sha256').update(fs.realpathSync(root)).digest('hex');
  return path.join(os.tmpdir(), 'code-flow', digest, 'bridge.json');
}

function selectionKey(fixed) {
  return crypto.createHash('sha256').update(JSON.stringify({
    path: process.env.PATH || '', node: fixed.node || '', entry: fixed.entry || ''
  })).digest('hex');
}

function readCache(root, key) {
  let data;
  try { data = JSON.parse(fs.readFileSync(cacheFile(root), 'utf8')); } catch (_) { return null; }
  if (!data || data.key !== key || typeof data.checked_at !== 'number' ||
      Date.now() - data.checked_at > CACHE_TTL_MS ||
      typeof data.entry_mtime !== 'number' || typeof data.candidate !== 'string' ||
      !data.capability || typeof data.capability !== 'object') return null;
  try { if (fs.statSync(data.capability.entry).mtimeMs !== data.entry_mtime) return null; }
  catch (_) { return null; }
  return validCapability(data.capability, data.candidate) ? data.capability : null;
}

function writeCache(root, key, selected) {
  try {
    const { candidate, ...capability } = selected;
    const entry_mtime = fs.statSync(capability.entry).mtimeMs;
    const file = cacheFile(root), temporary = file + '.' + process.pid + '.' + Date.now() + '.tmp';
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(temporary, JSON.stringify({ key, checked_at: Date.now(), entry_mtime,
      candidate, capability }), { mode: 0o600 });
    fs.renameSync(temporary, file);
  } catch (_) { /* best effort */ }
}

async function probePath(root, fixed, deadline) {
  for (const candidate of findOnPath(root)) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    const capability = await probe(root, candidate, remaining);
    if (capability) return { ...capability, candidate };
  }
  if (fixed.node && fixed.entry && fs.existsSync(fixed.node) && fs.existsSync(fixed.entry)) {
    const capability = { node: fixed.node, entry: fixed.entry, package: '@michaelxwb/code-flow',
      version: packageIdentity(fixed.entry)?.version, hook_protocol: 1 };
    if (validCapability(capability, fixed.entry)) return { ...capability, candidate: fixed.entry };
  }
  return null;
}

async function select(root, fixed, deadline) {
  const key = selectionKey(fixed), cached = readCache(root, key);
  if (cached) return cached;
  const selected = await probePath(root, fixed, deadline);
  if (selected) writeCache(root, key, selected);
  return selected;
}

function killTree(child) {
  if (!child.pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
    return;
  }
  try { process.kill(-child.pid, 'SIGKILL'); } catch (_) { try { child.kill('SIGKILL'); } catch (_) {} }
}

function run(root, selected, format, input, deadline) {
  return new Promise(resolve => {
    const chunks = [];
    let stderr = '', size = 0, settled = false, timer;
    const child = spawn(selected.node, [selected.entry, 'hook', 'prompt', '--format=' + format], {
      cwd: root, stdio: ['pipe', 'pipe', 'pipe'], detached: process.platform !== 'win32', windowsHide: true
    });
    const finish = ok => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      if (!ok) {
        if (stderr.trim()) process.stderr.write(stderr.trim() + '\n');
        resolve(null);
        return;
      }
      try {
        const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        resolve(normalizePayload(format, parsed));
      } catch (_) { resolve(null); }
    };
    timer = setTimeout(() => { killTree(child); finish(false); },
      Math.max(0, Math.min(TOTAL_MS, deadline - Date.now())));
    child.on('error', error => {
      stderr = (stderr + error.message).slice(-MAX_DIAGNOSTIC); finish(false);
    });
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_OUTPUT) { killTree(child); finish(false); }
      else chunks.push(chunk);
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-MAX_DIAGNOSTIC); });
    child.on('close', code => finish(code === 0));
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  });
}

function parseArgs(argv) {
  const fixed = { node: '', entry: '' }, options = {};
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === '--format') options.format = argv[++index];
    else if (argv[index] === '--node') fixed.node = argv[++index];
    else if (argv[index] === '--entry') fixed.entry = argv[++index];
  }
  return { fixed, format: options.format || 'claude' };
}

async function main() {
  const { fixed, format } = parseArgs(process.argv.slice(2));
  const root = process.cwd(), deadline = Date.now() + TOTAL_MS;
  const input = await readStdin(deadline);
  if (!input.trim()) return;
  const selected = await select(root, fixed, deadline - RUN_RESERVE_MS);
  if (!selected) {
    process.stderr.write('code-flow bridge: no valid global entry; run doctor\n');
    emit(format, emptyPayload(format));
    return;
  }
  const output = await run(root, selected, format, input, deadline);
  emit(format, output ?? emptyPayload(format));
}

main().catch(error => {
  process.stderr.write('code-flow bridge: ' + error.message + '\n');
  emit('claude', emptyPayload('claude'));
});
