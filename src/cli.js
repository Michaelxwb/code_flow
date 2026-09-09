#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const pkg = require('../package.json');
const specWorkflowMigration = require('./migrate/spec-workflow');

const usage = [
  'Usage: code-flow init [--force] [--platform=<claude|codex|costrict|opencode>] [--backup-dir=<path>]',
  '       code-flow migrate --spec-workflow <--dry-run|--prepare|--apply --plan <path>|--rollback <id>>',
  '       code-flow -v | --version',
  '       code-flow -h | --help'
].join('\n');

function printUsage(stream) {
  stream.write(`${usage}\n`);
}

function fail(message) {
  if (message) {
    process.stderr.write(`${message}\n`);
  }
  printUsage(process.stderr);
  process.exit(1);
}

function ensurePython3() {
  const probe = spawnSync('python3', ['--version'], { stdio: 'ignore' });
  if (probe.error || probe.status !== 0) {
    process.stderr.write('Error: python3 is required but was not found in PATH.\n');
    process.exit(1);
  }
}

// --- File classification ---

function fileCategory(relPath) {
  const p = relPath.replace(/\\/g, '/');
  if (p.startsWith('.claude/commands/')) return 'tool';
  if (p.startsWith('.costrict/commands/')) return 'tool';
  if (p.startsWith('.agents/skills/')) return 'tool';
  if (p.startsWith('.opencode/commands/')) return 'tool';
  if (p.startsWith('.code-flow/scripts/')) return 'tool';
  if (p === 'CLAUDE.md') return 'merge';
  if (p === 'AGENTS.md') return 'merge';
  if (p === '.claude/settings.local.json') return 'merge';
  if (p === '.costrict/settings.local.json') return 'merge';
  if (p === '.codex/hooks.json') return 'merge';
  if (p === '.code-flow/config.yml') return 'merge';
  if (p === '.codex/config.toml') return 'merge';
  if (p.startsWith('.opencode/plugins/')) return 'tool';
  if (p === 'opencode.json') return 'merge';
  return 'user';
}

// --- Version tracking ---

function readInstalledVersion(cwd) {
  const vFile = path.join(cwd, '.code-flow', '.version');
  if (!fs.existsSync(vFile)) return null;
  return fs.readFileSync(vFile, 'utf8').trim();
}

function writeVersion(cwd, version) {
  const vFile = path.join(cwd, '.code-flow', '.version');
  fs.mkdirSync(path.dirname(vFile), { recursive: true });
  fs.writeFileSync(vFile, version + '\n');
}

function compareVersions(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const va = pa[i] || 0;
    const vb = pb[i] || 0;
    if (va < vb) return -1;
    if (va > vb) return 1;
  }
  return 0;
}

function modeFor(installed, force) {
  if (force) return 'force';
  if (!installed) return 'fresh';
  if (compareVersions(installed, pkg.version) < 0) return 'upgrade';
  return 'current';
}

// Per-platform install records live beside the legacy global .version so one
// platform's upgrade never masks another platform's staleness.
function readAdapterVersions(cwd) {
  const file = path.join(cwd, '.code-flow', '.adapter-versions.json');
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (data && typeof data === 'object' && data.adapters && typeof data.adapters === 'object') {
      return { core: typeof data.core === 'string' ? data.core : null, adapters: data.adapters };
    }
  } catch (_) { /* missing or corrupt: fall through */ }
  return { core: null, adapters: {} };
}

function writeAdapterVersions(cwd, versions) {
  const file = path.join(cwd, '.code-flow', '.adapter-versions.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ core: versions.core, adapters: versions.adapters }, null, 2) + '\n');
}

// Marker dirs proving a platform was installed before per-platform tracking.
function platformFilesExist(cwd, platform) {
  const markers = {
    claude: ['.claude/commands'],
    codex: ['.agents/skills'],
    costrict: ['.costrict/commands'],
    opencode: ['.opencode/commands'],
  };
  return (markers[platform] || []).some(rel => fs.existsSync(path.join(cwd, rel)));
}

// --- Merge functions ---

// Replace fenced code blocks with same-length whitespace so byte offsets in
// the original text stay valid for slice operations downstream — but ## lines
// inside ```...``` no longer match the section regex.
function maskFencedCode(text) {
  return text.replace(/```[\s\S]*?```/g, block => block.replace(/[^\n]/g, ' '));
}

function mergeClaudeMd(srcFile, destFile) {
  const srcText = fs.readFileSync(srcFile, 'utf8');
  const destText = fs.readFileSync(destFile, 'utf8');
  const srcMasked = maskFencedCode(srcText);
  const destMasked = maskFencedCode(destText);

  const sectionRegex = /^## .+$/gm;
  const srcSections = [];
  let match;
  while ((match = sectionRegex.exec(srcMasked)) !== null) {
    srcSections.push({ heading: match[0].trim(), index: match.index });
  }

  const destSectionSet = new Set();
  const destRegex = /^## .+$/gm;
  while ((match = destRegex.exec(destMasked)) !== null) {
    destSectionSet.add(match[0].trim());
  }

  const missing = srcSections.filter(s => !destSectionSet.has(s.heading));
  if (missing.length === 0) return [];

  const additions = [];
  for (const { heading, index } of missing) {
    // Find next real section heading using the masked text, then slice the
    // original text by that offset so we keep any code-block content intact.
    const nextRel = srcMasked.slice(index + heading.length).search(/^## /m);
    const end = nextRel === -1 ? srcText.length : index + heading.length + nextRel;
    additions.push(srcText.slice(index, end).trimEnd());
  }

  const merged = destText.trimEnd() + '\n\n' + additions.join('\n\n') + '\n';
  fs.writeFileSync(destFile, merged);
  return missing.map(m => m.heading);
}

// Deep-merge a single hook event array. Each item has shape
//   { matcher?: string, hooks: [{ type, command, ... }] }
// We treat (matcher || '') as the identity key. New src items become new
// dest items; for existing items we union the inner hooks array by command
// string. User-added items / commands are never removed or rewritten — the
// merge is purely additive, in line with cli/code-standards.md "合并策略
// 必须保证用户自定义内容不被覆盖".
// If a future release changes a managed hook command string, add an explicit
// migration before merging; otherwise old and new commands will both run.
function mergeHookEventArray(srcArr, destArr, eventName, added) {
  if (!Array.isArray(srcArr) || !Array.isArray(destArr)) return;
  for (const srcItem of srcArr) {
    if (!srcItem || typeof srcItem !== 'object') continue;
    const srcMatcher = typeof srcItem.matcher === 'string' ? srcItem.matcher : '';
    const destItem = destArr.find(d => {
      if (!d || typeof d !== 'object') return false;
      const m = typeof d.matcher === 'string' ? d.matcher : '';
      return m === srcMatcher;
    });
    if (!destItem) {
      destArr.push(srcItem);
      added.push(`hook: ${eventName}${srcMatcher ? '@' + srcMatcher : ''}`);
      continue;
    }
    if (!Array.isArray(destItem.hooks)) destItem.hooks = [];
    const destCmds = new Set(
      destItem.hooks.map(h => (h && typeof h.command === 'string' ? h.command : ''))
    );
    for (const srcHook of (Array.isArray(srcItem.hooks) ? srcItem.hooks : [])) {
      if (!srcHook || typeof srcHook !== 'object') continue;
      const cmd = typeof srcHook.command === 'string' ? srcHook.command : '';
      if (destCmds.has(cmd)) continue;
      destItem.hooks.push(srcHook);
      destCmds.add(cmd);
      const tag = srcMatcher ? `${eventName}@${srcMatcher}` : eventName;
      added.push(`hook: ${tag} +${cmd.slice(0, 60)}`);
    }
  }
}

function mergeSettingsJson(srcFile, destFile) {
  const src = JSON.parse(fs.readFileSync(srcFile, 'utf8'));
  const dest = JSON.parse(fs.readFileSync(destFile, 'utf8'));
  const added = [];

  if (src.hooks && typeof src.hooks === 'object') {
    if (!dest.hooks || typeof dest.hooks !== 'object') dest.hooks = {};
    for (const event of Object.keys(src.hooks)) {
      const srcEvent = src.hooks[event];
      if (!dest.hooks[event]) {
        dest.hooks[event] = srcEvent;
        added.push(`hook: ${event}`);
        continue;
      }
      mergeHookEventArray(srcEvent, dest.hooks[event], event, added);
    }
  }

  for (const key of Object.keys(src)) {
    if (key === 'hooks') continue;
    if (!(key in dest)) {
      dest[key] = src[key];
      added.push(key);
    }
  }

  if (added.length > 0) {
    fs.writeFileSync(destFile, JSON.stringify(dest, null, 2) + '\n');
  }
  return added;
}

function mergeConfigYml(srcFile, destFile) {
  const srcText = fs.readFileSync(srcFile, 'utf8');
  const destText = fs.readFileSync(destFile, 'utf8');

  // Extract top-level keys (lines starting with a non-space char followed by colon)
  const topKeyRegex = /^([a-zA-Z_][a-zA-Z0-9_]*):/gm;
  const srcKeys = new Map();
  let m;
  while ((m = topKeyRegex.exec(srcText)) !== null) {
    srcKeys.set(m[1], m.index);
  }

  const destKeys = new Set();
  const destRegex = /^([a-zA-Z_][a-zA-Z0-9_]*):/gm;
  while ((m = destRegex.exec(destText)) !== null) {
    destKeys.add(m[1]);
  }

  const missing = [];
  const blocks = [];
  for (const [key, startIdx] of srcKeys) {
    if (destKeys.has(key)) continue;
    missing.push(key);
    // Extract the entire block for this key (until next top-level key or EOF)
    const remaining = srcText.slice(startIdx);
    const nextKey = remaining.indexOf('\n') !== -1
      ? remaining.slice(remaining.indexOf('\n') + 1).search(/^[a-zA-Z_]/m)
      : -1;
    const block = nextKey === -1
      ? remaining
      : remaining.slice(0, remaining.indexOf('\n') + 1 + nextKey);
    blocks.push(block.trimEnd());
  }

  if (blocks.length > 0) {
    const merged = destText.trimEnd() + '\n\n' + blocks.join('\n\n') + '\n';
    fs.writeFileSync(destFile, merged);
  }
  return missing;
}

function findTomlSectionBounds(lines, sectionName) {
  let start = -1;
  let end = lines.length;
  const header = new RegExp(`^\\s*\\[${sectionName}\\]\\s*$`);
  for (let i = 0; i < lines.length; i++) {
    if (!/^\s*\[.+\]\s*$/.test(lines[i])) continue;
    if (start !== -1) {
      end = i;
      break;
    }
    if (header.test(lines[i])) start = i;
  }
  return { start, end };
}

function findTomlKeyLine(lines, start, end, key) {
  const keyRegex = new RegExp(`^\\s*${key}\\s*=`);
  for (let i = start + 1; i < end; i++) {
    if (keyRegex.test(lines[i])) return i;
  }
  return -1;
}

function findFeatureInsertIndex(lines, start, end) {
  for (let i = start + 1; i < end; i++) {
    if (/^\s*$/.test(lines[i])) return i;
  }
  return end;
}

function mergeCodexConfigToml(srcFile, destFile) {
  const srcText = fs.readFileSync(srcFile, 'utf8');
  const destText = fs.readFileSync(destFile, 'utf8');
  const hookLineMatch = srcText.match(/^\s*hooks\s*=.*$/m);
  if (!hookLineMatch) return [];

  const lines = destText.split(/\n/);
  const { start, end } = findTomlSectionBounds(lines, 'features');

  if (start === -1) {
    fs.writeFileSync(destFile, destText.trimEnd() + '\n\n[features]\n' + hookLineMatch[0].trim() + '\n');
    return ['features.hooks'];
  }

  if (findTomlKeyLine(lines, start, end, 'hooks') !== -1) return [];

  const legacyIdx = findTomlKeyLine(lines, start, end, 'codex_hooks');
  if (legacyIdx !== -1) {
    lines[legacyIdx] = lines[legacyIdx].replace(/^(\s*)codex_hooks(\s*=.*)$/, '$1hooks$2');
    fs.writeFileSync(destFile, lines.join('\n').replace(/\n*$/, '\n'));
    return ['features.hooks'];
  }

  const insertAt = findFeatureInsertIndex(lines, start, end);
  lines.splice(insertAt, 0, hookLineMatch[0].trim());
  fs.writeFileSync(destFile, lines.join('\n').replace(/\n*$/, '\n'));
  return ['features.hooks'];
}

// --- File operations ---

function collectFiles(dir, base) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const rel = path.join(base, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectFiles(path.join(dir, entry.name), rel));
    } else if (entry.isFile()) {
      results.push(rel);
    }
  }
  return results;
}

function copyDirRecursive(srcDir, destDir, overwrite) {
  fs.mkdirSync(destDir, { recursive: true });
  const entries = fs.readdirSync(srcDir, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(srcDir, entry.name);
    const destPath = path.join(destDir, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath, overwrite);
      continue;
    }
    if (entry.isFile()) {
      if (overwrite || !fs.existsSync(destPath)) {
        fs.mkdirSync(path.dirname(destPath), { recursive: true });
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }
}

function copyFileIfMissing(srcFile, destFile) {
  if (fs.existsSync(destFile)) return;
  fs.mkdirSync(path.dirname(destFile), { recursive: true });
  fs.copyFileSync(srcFile, destFile);
}

function removeLegacyClaudeSkills(cwd, removed, opts) {
  // 0.1-era code-flow deployed its own skills (cf-*.md) under .claude/skills/.
  // Only those historically managed names may be touched; everything else is
  // user-owned and must survive init. Managed entries are backed up before
  // removal. The legacy dir belongs to the claude domain: other platforms
  // must never touch it.
  const options = opts || {};
  if (options.platform && options.platform !== 'claude') return;
  const legacySkills = path.join(cwd, '.claude', 'skills');
  if (!fs.existsSync(legacySkills)) return;

  let entries;
  try {
    entries = fs.readdirSync(legacySkills, { withFileTypes: true });
  } catch (error) {
    const code = error && error.code ? ` (${error.code})` : '';
    process.stderr.write(`Warning: failed to list deprecated .claude/skills/${code}; left untouched. Remove it manually.\n`);
    return;
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupRoot = options.backupDir
    ? path.resolve(cwd, options.backupDir)
    : path.join(cwd, '.code-flow', 'backups', stamp);
  for (const entry of entries) {
    if (!MANAGED_LEGACY_SKILL_NAMES.has(entry.name)) continue; // user-owned: keep
    const src = path.join(legacySkills, entry.name);
    const rel = path.join('.claude', 'skills', entry.name);
    try {
      const dest = path.join(backupRoot, rel);
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      if (entry.isDirectory()) {
        copyDirRecursive(src, dest, true);
      } else if (entry.isFile()) {
        fs.copyFileSync(src, dest);
      } else {
        continue;
      }
      fs.rmSync(src, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      removed.push(`${rel} (backup: ${path.relative(cwd, dest)})`);
    } catch (error) {
      const code = error && error.code ? ` (${error.code})` : '';
      const message = error && error.message ? error.message : String(error);
      process.stderr.write(`Warning: failed to migrate deprecated ${rel}${code}: ${message}\n`);
    }
  }
}

// Files renamed in 0.x → 1.x that may linger in upgraded projects.
// Each entry: { path: relative-to-cwd, replacedBy: hint string for the warning }.
const ORPHAN_FILES = [
  {
    path: '.code-flow/scripts/cf_codex_user_prompt_hook.py',
    replacedBy: '.code-flow/scripts/cf_user_prompt_hook.py',
  },
];

function removeOrphanFiles(cwd, removed) {
  for (const orphan of ORPHAN_FILES) {
    const abs = path.join(cwd, orphan.path);
    if (!fs.existsSync(abs)) continue;
    try {
      fs.unlinkSync(abs);
      removed.push(orphan.path);
    } catch (error) {
      const code = error && error.code ? ` (${error.code})` : '';
      process.stderr.write(
        `Warning: failed to remove orphan ${orphan.path}${code}; replaced by ${orphan.replacedBy}. Remove it manually.\n`
      );
    }
  }
}

// Skill entries historically deployed by code-flow 0.x under .claude/skills/.
// Only these names are managed legacy content; any other entry is user-owned.
const MANAGED_LEGACY_SKILL_NAMES = new Set([
  'cf-init.md',
  'cf-inject.md',
  'cf-learn.md',
  'cf-scan.md',
  'cf-stats.md',
  'cf-validate.md',
]);

// --- pyyaml dependency: probe first, fall back through PEP 668 strategies ---

// --- pyyaml dependency: probe first, fall back through PEP 668 strategies ---
// Bounded waits: each attempt carries its own timeout inside a total budget,
// with progress on stderr. spawnFn/logFn/nowFn are injectable for tests.
const PIP_PER_ATTEMPT_MS = 60000;
const PIP_TOTAL_MS = 120000;

function ensurePyYaml(spawnFn, logFn, nowFn) {
  const spawn = spawnFn || spawnSync;
  const log = logFn || ((message) => process.stderr.write(message));
  const now = nowFn || Date.now;
  const probe = spawn('python3', ['-c', 'import yaml'], { stdio: 'ignore' });
  if (!probe.error && probe.status === 0) return; // already installed

  const attempts = [
    ['-m', 'pip', 'install', '--user', 'pyyaml'],
    ['-m', 'pip', 'install', 'pyyaml'],
    ['-m', 'pip', 'install', '--user', '--break-system-packages', 'pyyaml'],
  ];
  const started = now();
  for (let i = 0; i < attempts.length; i++) {
    const remaining = PIP_TOTAL_MS - (now() - started);
    if (remaining <= 0) break;
    log(`Installing pyyaml (attempt ${i + 1}/${attempts.length})...\n`);
    const result = spawn('python3', attempts[i], {
      stdio: 'ignore',
      timeout: Math.min(PIP_PER_ATTEMPT_MS, remaining),
    });
    if (!result.error && result.status === 0) return;
  }
  log(
    'Warning: pyyaml install failed. Run manually:\n' +
    '  python3 -m pip install --user pyyaml\n' +
    '  # or, on PEP 668 systems:\n' +
    '  python3 -m pip install --user --break-system-packages pyyaml\n'
  );
}

// --- Adapter file installer: shared by every platform branch ---

// Install one adapter file with the standard create / force / upgrade /
// skip semantics. `mergeFn` is consulted only on upgrade for `merge`-class
// files; pass null for `tool`-class files (overwrite on upgrade) or for
// fresh-only files (skip on upgrade).
function installAdapterFile(opts) {
  const { src, dest, label, mode, mergeFn, toolOnUpgrade, results } = opts;
  if (!fs.existsSync(dest)) {
    results.created.push(label);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
    return;
  }
  if (mode === 'force') {
    results.updated.push(label);
    fs.copyFileSync(src, dest);
    return;
  }
  if (mode === 'upgrade') {
    if (toolOnUpgrade) {
      results.updated.push(label);
      fs.copyFileSync(src, dest);
      return;
    }
    if (mergeFn) {
      const added = mergeFn(src, dest);
      if (added.length > 0) {
        results.merged.push(`${label} — added: ${added.join(', ')}`);
      } else {
        results.skipped.push(label);
      }
      return;
    }
  }
  results.skipped.push(label);
}

// --- Platform argument parsing ---

function parsePlatform(args) {
  for (const arg of args) {
    if (arg.startsWith('--platform=')) {
      return arg.slice('--platform='.length);
    }
  }
  const idx = args.indexOf('--platform');
  if (idx !== -1) {
    return args[idx + 1] || '';
  }
  return null;
}

function parseStringFlag(args, name) {
  const prefix = `--${name}=`;
  for (const arg of args) {
    if (arg.startsWith(prefix)) return arg.slice(prefix.length);
  }
  const idx = args.indexOf(`--${name}`);
  if (idx !== -1) return args[idx + 1] || '';
  return '';
}

// --- Main init ---

function runInit(force, platform, opts) {
  const cwd = process.cwd();
  const options = opts || {};
  const installedVersion = readInstalledVersion(cwd);
  if (installedVersion && compareVersions(installedVersion, '0.4.2') >= 0 && compareVersions(installedVersion, '0.6.0') < 0) {
    process.stdout.write(`${JSON.stringify({ status: 'migration_required', version: installedVersion, command: 'code-flow migrate --spec-workflow --dry-run' })}\n`);
    process.exit(3);
  }
  ensurePython3();

  const baseDir = __dirname;
  const coreDir = path.join(baseDir, 'core');
  const adaptersDir = path.join(baseDir, 'adapters');

  // Determine mode: global mode drives core files and messaging; each
  // platform additionally resolves its own mode from per-platform records so
  // upgrading one platform can never mask another platform's staleness.
  // A global upgrade also refreshes the selected platform (previous behavior).
  const mode = modeFor(installedVersion, force);
  const adapterVersions = readAdapterVersions(cwd);
  const adapterPrev = typeof adapterVersions.adapters[platform] === 'string'
    ? adapterVersions.adapters[platform]
    : null;
  let platformMode;
  if (force) {
    platformMode = 'force';
  } else if (!adapterPrev && !platformFilesExist(cwd, platform)) {
    platformMode = 'fresh';
  } else if (
    (adapterPrev && compareVersions(adapterPrev, pkg.version) < 0) ||
    (!adapterPrev && platformFilesExist(cwd, platform)) ||
    mode === 'upgrade'
  ) {
    platformMode = 'upgrade';
  } else {
    platformMode = 'current';
  }

  const created = [];
  const updated = [];
  const merged = [];
  const skipped = [];
  const removed = [];
  const results = { created, updated, merged, skipped };

  // Track + copy helper for directory trees. dirMode is resolved per area:
  // core files follow the global mode, platform files follow platformMode.
  const processDir = (srcDir, destDir, prefix, dirMode) => {
    const effective = dirMode || mode;
    if (!fs.existsSync(srcDir)) return;
    const files = collectFiles(srcDir, '');
    for (const rel of files) {
      const src = path.join(srcDir, rel);
      const dest = path.join(destDir, rel);
      const label = path.join(prefix, rel);
      const cat = fileCategory(label);

      if (!fs.existsSync(dest)) {
        created.push(label);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(src, dest);
      } else if (effective === 'force') {
        updated.push(label);
        fs.copyFileSync(src, dest);
      } else if (effective === 'upgrade' && cat === 'tool') {
        updated.push(label);
        fs.copyFileSync(src, dest);
      } else {
        skipped.push(label);
      }
    }
  };

  // Process .code-flow/ (core)
  processDir(path.join(coreDir, 'code-flow'), path.join(cwd, '.code-flow'), '.code-flow', mode);

  // Process Claude adapter
  if (platform === 'claude') {
    installAdapterFile({
      src: path.join(adaptersDir, 'claude', 'CLAUDE.md'),
      dest: path.join(cwd, 'CLAUDE.md'),
      label: 'CLAUDE.md',
      mode: platformMode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    fs.mkdirSync(path.join(cwd, '.claude', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'claude', 'commands'),
      path.join(cwd, '.claude', 'commands'),
      '.claude/commands', platformMode
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'claude', 'settings.local.json'),
      dest: path.join(cwd, '.claude', 'settings.local.json'),
      label: '.claude/settings.local.json',
      mode: platformMode,
      mergeFn: mergeSettingsJson,
      toolOnUpgrade: false,
      results,
    });
  }

  // Process Costrict adapter
  if (platform === 'costrict') {
    installAdapterFile({
      src: path.join(adaptersDir, 'costrict', 'CLAUDE.md'),
      dest: path.join(cwd, 'CLAUDE.md'),
      label: 'CLAUDE.md',
      mode: platformMode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    fs.mkdirSync(path.join(cwd, '.costrict', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'costrict', 'commands'),
      path.join(cwd, '.costrict', 'commands'),
      '.costrict/commands', platformMode
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'costrict', 'settings.local.json'),
      dest: path.join(cwd, '.costrict', 'settings.local.json'),
      label: '.costrict/settings.local.json',
      mode: platformMode,
      mergeFn: mergeSettingsJson,
      toolOnUpgrade: false,
      results,
    });
  }

  // Process Codex adapter
  if (platform === 'codex') {
    installAdapterFile({
      src: path.join(adaptersDir, 'codex', 'AGENTS.md'),
      dest: path.join(cwd, 'AGENTS.md'),
      label: 'AGENTS.md',
      mode: platformMode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    installAdapterFile({
      src: path.join(adaptersDir, 'codex', 'hooks.json'),
      dest: path.join(cwd, '.codex', 'hooks.json'),
      label: '.codex/hooks.json',
      mode: platformMode,
      mergeFn: mergeSettingsJson,
      toolOnUpgrade: false,
      results,
    });

    installAdapterFile({
      src: path.join(adaptersDir, 'codex', 'config.toml'),
      dest: path.join(cwd, '.codex', 'config.toml'),
      label: '.codex/config.toml',
      mode: platformMode,
      mergeFn: mergeCodexConfigToml,
      toolOnUpgrade: false,
      results,
    });

    // Project-level .agents/skills/ (version-controlled, committed to repo)
    processDir(
      path.join(adaptersDir, 'codex', 'skills'),
      path.join(cwd, '.agents', 'skills'),
      '.agents/skills', platformMode
    );
  }

  // Process OpenCode adapter
  if (platform === 'opencode') {
    installAdapterFile({
      src: path.join(adaptersDir, 'opencode', 'AGENTS.md'),
      dest: path.join(cwd, 'AGENTS.md'),
      label: 'AGENTS.md',
      mode: platformMode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    // Plugin files under .opencode/plugins/code-flow/
    processDir(
      path.join(adaptersDir, 'opencode', 'plugins'),
      path.join(cwd, '.opencode', 'plugins'),
      '.opencode/plugins', platformMode
    );

    // Stamp main package version into the plugin's package.json
    const pluginPkgPath = path.join(cwd, '.opencode', 'plugins', 'code-flow', 'package.json');
    if (fs.existsSync(pluginPkgPath)) {
      const pluginPkg = JSON.parse(fs.readFileSync(pluginPkgPath, 'utf8'));
      pluginPkg.version = pkg.version;
      fs.writeFileSync(pluginPkgPath, JSON.stringify(pluginPkg, null, 2) + '\n');
    }

    // Command files under .opencode/commands/
    processDir(
      path.join(adaptersDir, 'opencode', 'commands'),
      path.join(cwd, '.opencode', 'commands'),
      '.opencode/commands', platformMode
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'opencode', 'opencode.json'),
      dest: path.join(cwd, 'opencode.json'),
      label: 'opencode.json',
      mode: platformMode,
      mergeFn: mergeSettingsJson,
      toolOnUpgrade: false,
      results,
    });
  }

  // Merge config.yml on upgrade
  const configSrc = path.join(coreDir, 'code-flow', 'config.yml');
  const configDest = path.join(cwd, '.code-flow', 'config.yml');
  if (mode === 'upgrade' && fs.existsSync(configDest) && fs.existsSync(configSrc)) {
    const added = mergeConfigYml(configSrc, configDest);
    if (added.length > 0) {
      // Replace the skipped entry with merged
      const idx = skipped.indexOf('.code-flow/config.yml');
      if (idx !== -1) skipped.splice(idx, 1);
      merged.push(`.code-flow/config.yml — added: ${added.join(', ')}`);
    }
  }

  // Clean up legacy .claude/skills/ (claude domain only; user-owned kept, managed backed up)
  removeLegacyClaudeSkills(cwd, removed, { platform, backupDir: options.backupDir || '' });

  // Clean up renamed orphan scripts (only meaningful on upgrade)
  if (mode === 'upgrade' || mode === 'force') {
    removeOrphanFiles(cwd, removed);
  }

  // Install pyyaml — probe first, fall back through PEP 668 strategies
  ensurePyYaml();

  // Write version (legacy global file kept for compatibility) + per-platform records
  writeVersion(cwd, pkg.version);
  adapterVersions.adapters[platform] = pkg.version;
  adapterVersions.core = pkg.version;
  writeAdapterVersions(cwd, adapterVersions);

  // Output summary
  if (mode === 'upgrade') {
    process.stdout.write(`\ncode-flow upgraded: ${installedVersion} → ${pkg.version}\n\n`);
  } else if (mode === 'current' && platformMode === 'current' && created.length === 0 && updated.length === 0 && merged.length === 0) {
    process.stdout.write(`code-flow v${pkg.version} already up to date.\n`);
    process.exit(0);
  } else if (mode === 'force') {
    process.stdout.write(`\ncode-flow v${pkg.version} force-initialized!\n\n`);
  } else {
    process.stdout.write(`\ncode-flow v${pkg.version} initialized!\n\n`);
  }

  if (updated.length > 0) {
    process.stdout.write('Updated (tool-managed):\n');
    for (const f of updated) process.stdout.write(`  ↑ ${f}\n`);
  }
  if (merged.length > 0) {
    process.stdout.write('Merged (new sections added):\n');
    for (const f of merged) process.stdout.write(`  ⊕ ${f}\n`);
  }
  if (created.length > 0) {
    process.stdout.write('Created:\n');
    for (const f of created) process.stdout.write(`  + ${f}\n`);
  }
  if (skipped.length > 0) {
    process.stdout.write('Skipped (user-customized):\n');
    for (const f of skipped) process.stdout.write(`  · ${f}\n`);
  }
  if (removed.length > 0) {
    process.stdout.write('Removed (deprecated):\n');
    for (const f of removed) process.stdout.write(`  ✕ ${f}\n`);
  }

  process.stdout.write('\nNext steps:\n');
  if (platform === 'codex') {
    if (mode === 'fresh') {
      process.stdout.write('  1. Edit AGENTS.md — fill in team/project info\n');
      process.stdout.write('  2. Run /hooks in Codex CLI and trust the code-flow hooks if prompted\n');
      process.stdout.write('  3. Run $cf-init in Codex CLI to auto-scan and populate specs\n');
      process.stdout.write('     Or manually edit .code-flow/specs/ to fill in your coding standards\n');
    } else {
      process.stdout.write('  Run /hooks in Codex CLI and trust changed code-flow hooks if prompted\n');
      process.stdout.write('  Run $cf-learn in Codex CLI to update specs with project conventions\n');
      process.stdout.write('  Run $cf-learn --map to update retrieval maps\n');
    }
  } else if (platform === 'costrict') {
    if (mode === 'fresh') {
      process.stdout.write('  1. Edit CLAUDE.md — fill in team/project info\n');
      process.stdout.write('  2. Run /cf-init in Costrict to auto-scan and populate specs\n');
      process.stdout.write('     Or manually edit .code-flow/specs/ to fill in your coding standards\n');
    } else {
      process.stdout.write('  Run /cf-learn in Costrict to update specs with project conventions\n');
      process.stdout.write('  Run /cf-learn --map to update retrieval maps\n');
    }
  } else if (platform === 'opencode') {
    if (mode === 'fresh') {
      process.stdout.write('  1. Edit AGENTS.md — fill in team/project info\n');
      process.stdout.write('  2. Start opencode in this directory — the plugin auto-loads\n');
      process.stdout.write('  3. Run /cf-init in OpenCode to auto-scan and populate specs\n');
      process.stdout.write('     Or manually edit .code-flow/specs/ to fill in your coding standards\n');
    } else {
      process.stdout.write('  Run /cf-learn in OpenCode to update specs with project conventions\n');
      process.stdout.write('  Run /cf-learn --map to update retrieval maps\n');
    }
  } else {
    if (mode === 'fresh') {
      process.stdout.write('  1. Edit CLAUDE.md — fill in team/project info\n');
      process.stdout.write('  2. Run /cf-init in Claude Code to auto-scan and populate specs\n');
      process.stdout.write('     Or manually edit .code-flow/specs/ to fill in your coding standards\n');
    } else {
      process.stdout.write('  Run /cf-learn in Claude Code to update specs with project conventions\n');
      process.stdout.write('  Run /cf-learn --map to update retrieval maps\n');
    }
  }
  process.exit(0);
}

// --- CLI argument parsing ---

const args = process.argv.slice(2);

function argumentValue(values, name) {
  const index = values.indexOf(name);
  return index >= 0 ? values[index + 1] || '' : '';
}

function migrationExitCode(result) {
  if (result.status === 'rolled_back') return 4;
  if (result.status === 'recovery_required') return 5;
  if (result.status === 'prepared_blocked') return 3;
  return 0;
}

function runMigrate(values) {
  if (!values.includes('--spec-workflow')) fail('Error: migrate requires --spec-workflow.');
  const actions = ['--dry-run', '--prepare', '--apply', '--rollback'].filter(action => values.includes(action));
  if (actions.length !== 1) fail('Error: choose exactly one migrate action.');
  let result;
  try {
    if (actions[0] === '--dry-run') result = specWorkflowMigration.preview(process.cwd());
    if (actions[0] === '--prepare') result = specWorkflowMigration.prepare(process.cwd());
    if (actions[0] === '--apply') {
      const plan = argumentValue(values, '--plan');
      if (!plan) fail('Error: --apply requires --plan <path>.');
      result = specWorkflowMigration.apply(path.resolve(plan));
    }
    if (actions[0] === '--rollback') {
      const id = argumentValue(values, '--rollback');
      if (!id) fail('Error: --rollback requires a migration id.');
      const plan = path.join(process.cwd(), '.code-flow', 'migrations', id, 'migration-plan.json');
      result = specWorkflowMigration.rollback(plan);
    }
    process.stdout.write(`${JSON.stringify(result)}\n`);
    process.exit(migrationExitCode(result));
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ status: 'unresolved', error: String(error.message || error) })}\n`);
    process.exit(3);
  }
}

if (args.includes('-v') || args.includes('--version')) {
  process.stdout.write(`${pkg.version}\n`);
  process.exit(0);
}

if (args.includes('-h') || args.includes('--help')) {
  process.stdout.write(`code-flow v${pkg.version}\n\n`);
  printUsage(process.stdout);
  process.exit(0);
}

if (args[0] === 'init') {
  const force = args.includes('--force');
  const rawPlatform = parsePlatform(args);
  const platform = rawPlatform === null ? 'claude' : rawPlatform;
  if (platform !== 'claude' && platform !== 'codex' && platform !== 'costrict' && platform !== 'opencode') {
    fail(`Error: --platform must be "claude", "codex", "costrict", or "opencode", got "${platform}".`);
  }
  runInit(force, platform, { backupDir: parseStringFlag(args, 'backup-dir') });
}

if (args[0] === 'migrate') {
  runMigrate(args.slice(1));
}

if (args.length === 0) {
  fail('Error: missing command.');
}

if (args.includes('--path')) {
  fail('Error: --path is not supported; run init in the current directory.');
}

fail(`Error: unknown command "${args.join(' ')}".`);
