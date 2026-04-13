#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const pkg = require('../package.json');

const usage = [
  'Usage: code-flow init [--force] [--platform=<claude|codex|costrict>]',
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
  if (relPath.startsWith('.costrict/commands/')) return 'tool';
  if (relPath.startsWith('.agents/skills/')) return 'tool';
  if (relPath.startsWith('.code-flow/scripts/')) return 'tool';
  if (relPath === 'CLAUDE.md') return 'merge';
  if (relPath === 'AGENTS.md') return 'merge';
  if (relPath === '.claude/settings.local.json') return 'merge';
  if (relPath === '.costrict/settings.local.json') return 'merge';
  if (relPath === '.codex/hooks.json') return 'tool';
  if (relPath === '.code-flow/config.yml') return 'merge';
  if (relPath === '.codex/config.toml') return 'tool';
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

    fs.mkdirSync(path.join(cwd, '.claude', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'claude', 'commands'),
      path.join(cwd, '.claude', 'commands'),
      '.claude/commands'
    );

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
  }

  // Process Costrict adapter
  if (platform === 'costrict') {
    const costrictMdSrc = path.join(adaptersDir, 'costrict', 'AGENTS.md');
    const costrictMdDest = path.join(cwd, 'AGENTS.md');
    if (!fs.existsSync(costrictMdDest)) {
      created.push('AGENTS.md');
      fs.copyFileSync(costrictMdSrc, costrictMdDest);
    } else if (mode === 'force') {
      updated.push('AGENTS.md');
      fs.copyFileSync(costrictMdSrc, costrictMdDest);
    } else if (mode === 'upgrade') {
      const added = mergeClaudeMd(costrictMdSrc, costrictMdDest);
      if (added.length > 0) {
        merged.push(`AGENTS.md — added: ${added.join(', ')}`);
      } else {
        skipped.push('AGENTS.md');
      }
    } else {
      skipped.push('AGENTS.md');
    }

    fs.mkdirSync(path.join(cwd, '.costrict', 'commands'), { recursive: true });
    processDir(
      path.join(adaptersDir, 'costrict', 'commands'),
      path.join(cwd, '.costrict', 'commands'),
      '.costrict/commands'
    );

    const settingsSrc = path.join(adaptersDir, 'costrict', 'settings.local.json');
    const settingsDest = path.join(cwd, '.costrict', 'settings.local.json');
    if (!fs.existsSync(settingsDest)) {
      created.push('.costrict/settings.local.json');
      fs.mkdirSync(path.dirname(settingsDest), { recursive: true });
      fs.copyFileSync(settingsSrc, settingsDest);
    } else if (mode === 'force') {
      updated.push('.costrict/settings.local.json');
      fs.copyFileSync(settingsSrc, settingsDest);
    } else if (mode === 'upgrade') {
      const added = mergeSettingsJson(settingsSrc, settingsDest);
      if (added.length > 0) {
        merged.push(`.costrict/settings.local.json — added: ${added.join(', ')}`);
      } else {
        skipped.push('.costrict/settings.local.json');
      }
    } else {
      skipped.push('.costrict/settings.local.json');
    }
  }

  // Process Codex adapter
  if (platform === 'codex') {
    const agentsMdSrc = path.join(adaptersDir, 'codex', 'AGENTS.md');
    const agentsMdDest = path.join(cwd, 'AGENTS.md');
    if (!fs.existsSync(agentsMdDest)) {
      created.push('AGENTS.md');
      fs.copyFileSync(agentsMdSrc, agentsMdDest);
    } else if (mode === 'force') {
      updated.push('AGENTS.md');
      fs.copyFileSync(agentsMdSrc, agentsMdDest);
    } else if (mode === 'upgrade') {
      const added = mergeClaudeMd(agentsMdSrc, agentsMdDest);
      if (added.length > 0) {
        merged.push(`AGENTS.md — added: ${added.join(', ')}`);
      } else {
        skipped.push('AGENTS.md');
      }
    } else {
      skipped.push('AGENTS.md');
    }

    const codexHooksSrc = path.join(adaptersDir, 'codex', 'hooks.json');
    const codexHooksDest = path.join(cwd, '.codex', 'hooks.json');
    if (!fs.existsSync(codexHooksDest)) {
      created.push('.codex/hooks.json');
      fs.mkdirSync(path.dirname(codexHooksDest), { recursive: true });
      fs.copyFileSync(codexHooksSrc, codexHooksDest);
    } else if (mode === 'force' || mode === 'upgrade') {
      updated.push('.codex/hooks.json');
      fs.copyFileSync(codexHooksSrc, codexHooksDest);
    } else {
      skipped.push('.codex/hooks.json');
    }

    const codexConfigSrc = path.join(adaptersDir, 'codex', 'config.toml');
    const codexConfigDest = path.join(cwd, '.codex', 'config.toml');
    if (!fs.existsSync(codexConfigDest)) {
      created.push('.codex/config.toml');
      fs.mkdirSync(path.dirname(codexConfigDest), { recursive: true });
      fs.copyFileSync(codexConfigSrc, codexConfigDest);
    } else if (mode === 'force' || mode === 'upgrade') {
      updated.push('.codex/config.toml');
      fs.copyFileSync(codexConfigSrc, codexConfigDest);
    } else {
      skipped.push('.codex/config.toml');
    }

    const codexSkillsSrc = path.join(adaptersDir, 'codex', 'skills');

    // Project-level .agents/skills/ (version-controlled, committed to repo)
    processDir(codexSkillsSrc, path.join(cwd, '.agents', 'skills'), '.agents/skills');
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
  if (platform !== 'claude' && platform !== 'codex' && platform !== 'costrict') {
    fail(`Error: --platform must be "claude", "codex", or "costrict", got "${platform}".`);
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
