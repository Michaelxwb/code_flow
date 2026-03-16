#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const pkg = require('../package.json');

const usage = [
  'Usage: code-flow init [--force]',
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
  if (relPath.startsWith('.claude/commands/')) return 'tool';
  if (relPath.startsWith('.code-flow/scripts/')) return 'tool';
  if (relPath === 'CLAUDE.md') return 'merge';
  if (relPath === '.claude/settings.local.json') return 'merge';
  if (relPath === '.code-flow/config.yml') return 'merge';
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

function mergeClaudeMd(srcFile, destFile) {
  const srcText = fs.readFileSync(srcFile, 'utf8');
  const destText = fs.readFileSync(destFile, 'utf8');

  const sectionRegex = /^## .+$/gm;
  const srcSections = [];
  let match;
  while ((match = sectionRegex.exec(srcText)) !== null) {
    srcSections.push(match[0].trim());
  }

  const destSectionSet = new Set();
  const destRegex = /^## .+$/gm;
  while ((match = destRegex.exec(destText)) !== null) {
    destSectionSet.add(match[0].trim());
  }

  const missing = srcSections.filter(s => !destSectionSet.has(s));
  if (missing.length === 0) return [];

  const additions = [];
  for (const heading of missing) {
    const idx = srcText.indexOf(heading);
    const nextHeadingIdx = srcText.indexOf('\n## ', idx + 1);
    const block = nextHeadingIdx === -1
      ? srcText.slice(idx)
      : srcText.slice(idx, nextHeadingIdx);
    additions.push(block.trimEnd());
  }

  const merged = destText.trimEnd() + '\n\n' + additions.join('\n\n') + '\n';
  fs.writeFileSync(destFile, merged);
  return missing;
}

function mergeSettingsJson(srcFile, destFile) {
  const src = JSON.parse(fs.readFileSync(srcFile, 'utf8'));
  const dest = JSON.parse(fs.readFileSync(destFile, 'utf8'));
  const added = [];

  // Merge hooks
  if (src.hooks) {
    if (!dest.hooks) dest.hooks = {};
    for (const event of Object.keys(src.hooks)) {
      if (!dest.hooks[event]) {
        dest.hooks[event] = src.hooks[event];
        added.push(`hook: ${event}`);
      }
    }
  }

  // Merge other top-level keys
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

// --- Main init ---

function runInit(force) {
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

  // Process CLAUDE.md
  const claudeMdSrc = path.join(adaptersDir, 'claude', 'CLAUDE.md');
  const claudeMdDest = path.join(cwd, 'CLAUDE.md');
  if (!fs.existsSync(claudeMdDest)) {
    created.push('CLAUDE.md');
    fs.copyFileSync(claudeMdSrc, claudeMdDest);
  } else if (mode === 'force') {
    updated.push('CLAUDE.md');
    fs.copyFileSync(claudeMdSrc, claudeMdDest);
  } else if (mode === 'upgrade') {
    const added = mergeClaudeMd(claudeMdSrc, claudeMdDest);
    if (added.length > 0) {
      merged.push(`CLAUDE.md — added: ${added.join(', ')}`);
    } else {
      skipped.push('CLAUDE.md');
    }
  } else {
    skipped.push('CLAUDE.md');
  }

  // Process .claude/commands/
  fs.mkdirSync(path.join(cwd, '.claude', 'commands'), { recursive: true });
  processDir(
    path.join(adaptersDir, 'claude', 'commands'),
    path.join(cwd, '.claude', 'commands'),
    '.claude/commands'
  );

  // Process settings.local.json
  const settingsSrc = path.join(adaptersDir, 'claude', 'settings.local.json');
  const settingsDest = path.join(cwd, '.claude', 'settings.local.json');
  if (!fs.existsSync(settingsDest)) {
    created.push('.claude/settings.local.json');
    fs.mkdirSync(path.dirname(settingsDest), { recursive: true });
    fs.copyFileSync(settingsSrc, settingsDest);
  } else if (mode === 'force') {
    updated.push('.claude/settings.local.json');
    fs.copyFileSync(settingsSrc, settingsDest);
  } else if (mode === 'upgrade') {
    const added = mergeSettingsJson(settingsSrc, settingsDest);
    if (added.length > 0) {
      merged.push(`.claude/settings.local.json — added: ${added.join(', ')}`);
    } else {
      skipped.push('.claude/settings.local.json');
    }
  } else {
    skipped.push('.claude/settings.local.json');
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
  const legacySkills = path.join(cwd, '.claude', 'skills');
  if (fs.existsSync(legacySkills)) {
    fs.rmSync(legacySkills, { recursive: true });
    removed.push('.claude/skills/');
  }

  // Install pyyaml
  const pip = spawnSync('python3', ['-m', 'pip', 'install', 'pyyaml'], {
    stdio: 'ignore'
  });
  if (pip.error || pip.status !== 0) {
    process.stderr.write('Warning: pyyaml install failed. Run manually: pip install pyyaml\n');
  }

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

  if (mode === 'fresh') {
    process.stdout.write('\nNext steps:\n');
    process.stdout.write('  1. Edit CLAUDE.md — fill in team/project info\n');
    process.stdout.write('  2. Edit .code-flow/specs/ — fill in your coding standards\n');
    process.stdout.write('  3. Run /cf-learn in Claude Code to auto-discover constraints\n');
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
  runInit(force);
}

if (args.length === 0) {
  fail('Error: missing command.');
}

if (args.includes('--path')) {
  fail('Error: --path is not supported; run init in the current directory.');
}

fail(`Error: unknown command "${args.join(' ')}".`);
