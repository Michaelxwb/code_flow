#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const pkg = require('../package.json');

const usage = [
  'Usage: code-flow init [--force] [--platform=<claude|codex|costrict|opencode>]',
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
  if (p === '.codex/hooks.json') return 'tool';
  if (p === '.code-flow/config.yml') return 'merge';
  if (p === '.codex/config.toml') return 'tool';
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

function removeLegacyClaudeSkills(cwd, removed) {
  const legacySkills = path.join(cwd, '.claude', 'skills');
  if (!fs.existsSync(legacySkills)) return;

  try {
    fs.rmSync(legacySkills, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 100
    });
    if (!fs.existsSync(legacySkills)) {
      removed.push('.claude/skills/');
      return;
    }
  } catch (error) {
    const code = error && error.code ? ` (${error.code})` : '';
    const message = error && error.message ? error.message : String(error);
    process.stderr.write(`Warning: failed to remove deprecated .claude/skills/${code}: ${message}\n`);
    return;
  }

  process.stderr.write('Warning: failed to remove deprecated .claude/skills/. Remove it manually.\n');
}

// --- pyyaml dependency: probe first, fall back through PEP 668 strategies ---

function ensurePyYaml() {
  const probe = spawnSync('python3', ['-c', 'import yaml'], { stdio: 'ignore' });
  if (!probe.error && probe.status === 0) return; // already installed

  const attempts = [
    ['-m', 'pip', 'install', '--user', 'pyyaml'],
    ['-m', 'pip', 'install', 'pyyaml'],
    ['-m', 'pip', 'install', '--user', '--break-system-packages', 'pyyaml'],
  ];
  for (const args of attempts) {
    const result = spawnSync('python3', args, { stdio: 'ignore' });
    if (!result.error && result.status === 0) return;
  }
  process.stderr.write(
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

// --- Main init ---

function runInit(force, platform) {
  ensurePython3();

  const cwd = process.cwd();
  const baseDir = __dirname;
  const coreDir = path.join(baseDir, 'core');
  const adaptersDir = path.join(baseDir, 'adapters');

  // Determine mode
  const installedVersion = readInstalledVersion(cwd);
  let mode;
  if (force) {
    mode = 'force';
  } else if (!installedVersion) {
    mode = 'fresh';
  } else if (compareVersions(installedVersion, pkg.version) < 0) {
    mode = 'upgrade';
  } else {
    mode = 'current';
  }

  const created = [];
  const updated = [];
  const merged = [];
  const skipped = [];
  const removed = [];
  const results = { created, updated, merged, skipped };

  // Track + copy helper for directory trees
  const processDir = (srcDir, destDir, prefix) => {
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
      } else if (mode === 'force') {
        updated.push(label);
        fs.copyFileSync(src, dest);
      } else if (mode === 'upgrade' && cat === 'tool') {
        updated.push(label);
        fs.copyFileSync(src, dest);
      } else {
        skipped.push(label);
      }
    }
  };

  // Process .code-flow/ (core)
  processDir(path.join(coreDir, 'code-flow'), path.join(cwd, '.code-flow'), '.code-flow');

  // Process Claude adapter
  if (platform === 'claude') {
    installAdapterFile({
      src: path.join(adaptersDir, 'claude', 'CLAUDE.md'),
      dest: path.join(cwd, 'CLAUDE.md'),
      label: 'CLAUDE.md',
      mode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    fs.mkdirSync(path.join(cwd, '.claude', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'claude', 'commands'),
      path.join(cwd, '.claude', 'commands'),
      '.claude/commands'
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'claude', 'settings.local.json'),
      dest: path.join(cwd, '.claude', 'settings.local.json'),
      label: '.claude/settings.local.json',
      mode,
      mergeFn: mergeSettingsJson,
      toolOnUpgrade: false,
      results,
    });
  }

  // Process Costrict adapter
  if (platform === 'costrict') {
    installAdapterFile({
      src: path.join(adaptersDir, 'costrict', 'AGENTS.md'),
      dest: path.join(cwd, 'AGENTS.md'),
      label: 'AGENTS.md',
      mode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    fs.mkdirSync(path.join(cwd, '.costrict', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'costrict', 'commands'),
      path.join(cwd, '.costrict', 'commands'),
      '.costrict/commands'
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'costrict', 'settings.local.json'),
      dest: path.join(cwd, '.costrict', 'settings.local.json'),
      label: '.costrict/settings.local.json',
      mode,
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
      mode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    installAdapterFile({
      src: path.join(adaptersDir, 'codex', 'hooks.json'),
      dest: path.join(cwd, '.codex', 'hooks.json'),
      label: '.codex/hooks.json',
      mode,
      mergeFn: null,
      toolOnUpgrade: true,
      results,
    });

    installAdapterFile({
      src: path.join(adaptersDir, 'codex', 'config.toml'),
      dest: path.join(cwd, '.codex', 'config.toml'),
      label: '.codex/config.toml',
      mode,
      mergeFn: null,
      toolOnUpgrade: true,
      results,
    });

    // Project-level .agents/skills/ (version-controlled, committed to repo)
    processDir(
      path.join(adaptersDir, 'codex', 'skills'),
      path.join(cwd, '.agents', 'skills'),
      '.agents/skills'
    );
  }

  // Process OpenCode adapter
  if (platform === 'opencode') {
    installAdapterFile({
      src: path.join(adaptersDir, 'opencode', 'AGENTS.md'),
      dest: path.join(cwd, 'AGENTS.md'),
      label: 'AGENTS.md',
      mode,
      mergeFn: mergeClaudeMd,
      toolOnUpgrade: false,
      results,
    });

    // Plugin files under .opencode/plugins/code-flow/
    processDir(
      path.join(adaptersDir, 'opencode', 'plugins'),
      path.join(cwd, '.opencode', 'plugins'),
      '.opencode/plugins'
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
      '.opencode/commands'
    );

    installAdapterFile({
      src: path.join(adaptersDir, 'opencode', 'opencode.json'),
      dest: path.join(cwd, 'opencode.json'),
      label: 'opencode.json',
      mode,
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

  // Clean up legacy .claude/skills/
  removeLegacyClaudeSkills(cwd, removed);

  // Clean up renamed orphan scripts (only meaningful on upgrade)
  if (mode === 'upgrade' || mode === 'force') {
    removeOrphanFiles(cwd, removed);
  }

  // Install pyyaml — probe first, fall back through PEP 668 strategies
  ensurePyYaml();

  // Write version
  writeVersion(cwd, pkg.version);

  // Output summary
  if (mode === 'upgrade') {
    process.stdout.write(`\ncode-flow upgraded: ${installedVersion} → ${pkg.version}\n\n`);
  } else if (mode === 'current' && created.length === 0 && updated.length === 0 && merged.length === 0) {
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
      process.stdout.write('  2. Run $cf-init in Codex CLI to auto-scan and populate specs\n');
      process.stdout.write('     Or manually edit .code-flow/specs/ to fill in your coding standards\n');
    } else {
      process.stdout.write('  Run $cf-learn in Codex CLI to update specs with project conventions\n');
      process.stdout.write('  Run $cf-learn --map to update retrieval maps\n');
    }
  } else if (platform === 'costrict') {
    if (mode === 'fresh') {
      process.stdout.write('  1. Edit AGENTS.md — fill in team/project info\n');
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
  runInit(force, platform);
}

if (args.length === 0) {
  fail('Error: missing command.');
}

if (args.includes('--path')) {
  fail('Error: --path is not supported; run init in the current directory.');
}

fail(`Error: unknown command "${args.join(' ')}".`);
