#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const pkg = require('../package.json');

const usage = [
  'Usage: code-flow init',
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

function copyFileIfMissing(srcFile, destFile) {
  if (fs.existsSync(destFile)) {
    return;
  }
  fs.mkdirSync(path.dirname(destFile), { recursive: true });
  fs.copyFileSync(srcFile, destFile);
}

function copyDirRecursive(srcDir, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  const entries = fs.readdirSync(srcDir, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(srcDir, entry.name);
    const destPath = path.join(destDir, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
      continue;
    }
    if (entry.isFile()) {
      if (!fs.existsSync(destPath)) {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }
}

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

function runInit() {
  ensurePython3();

  const cwd = process.cwd();
  const baseDir = __dirname;
  const coreDir = path.join(baseDir, 'core');
  const adaptersDir = path.join(baseDir, 'adapters');

  const created = [];
  const skipped = [];

  // Track files before copy
  const track = (srcDir, destDir, prefix) => {
    if (!fs.existsSync(srcDir)) return;
    const files = collectFiles(srcDir, '');
    for (const rel of files) {
      const dest = path.join(destDir, rel);
      const label = path.join(prefix, rel);
      if (fs.existsSync(dest)) {
        skipped.push(label);
      } else {
        created.push(label);
      }
    }
  };

  track(path.join(coreDir, 'code-flow'), path.join(cwd, '.code-flow'), '.code-flow');
  const claudeMdDest = path.join(cwd, 'CLAUDE.md');
  if (fs.existsSync(claudeMdDest)) {
    skipped.push('CLAUDE.md');
  } else {
    created.push('CLAUDE.md');
  }
  track(path.join(adaptersDir, 'claude', 'commands'), path.join(cwd, '.claude', 'commands'), '.claude/commands');
  const settingsDest = path.join(cwd, '.claude', 'settings.local.json');
  if (fs.existsSync(settingsDest)) {
    skipped.push('.claude/settings.local.json');
  } else {
    created.push('.claude/settings.local.json');
  }

  // Perform copy
  copyDirRecursive(path.join(coreDir, 'code-flow'), path.join(cwd, '.code-flow'));
  copyFileIfMissing(path.join(adaptersDir, 'claude', 'CLAUDE.md'), claudeMdDest);
  fs.mkdirSync(path.join(cwd, '.claude', 'commands'), { recursive: true });
  copyDirRecursive(path.join(adaptersDir, 'claude', 'commands'), path.join(cwd, '.claude', 'commands'));
  copyFileIfMissing(path.join(adaptersDir, 'claude', 'settings.local.json'), settingsDest);

  // Clean up legacy .claude/skills/ if it exists
  const legacySkills = path.join(cwd, '.claude', 'skills');
  if (fs.existsSync(legacySkills)) {
    fs.rmSync(legacySkills, { recursive: true });
    process.stdout.write('Cleaned up legacy .claude/skills/\n');
  }

  // Install pyyaml
  const pip = spawnSync('python3', ['-m', 'pip', 'install', 'pyyaml'], {
    stdio: 'ignore'
  });
  if (pip.error || pip.status !== 0) {
    process.stderr.write('Warning: pyyaml install failed. Run manually: pip install pyyaml\n');
  }

  // Output summary
  process.stdout.write('\ncode-flow initialized!\n\n');
  if (created.length > 0) {
    process.stdout.write('Created:\n');
    for (const f of created) {
      process.stdout.write(`  + ${f}\n`);
    }
  }
  if (skipped.length > 0) {
    process.stdout.write('Skipped (already exist):\n');
    for (const f of skipped) {
      process.stdout.write(`  - ${f}\n`);
    }
  }
  process.stdout.write('\nNext steps:\n');
  process.stdout.write('  1. Edit CLAUDE.md — fill in team/project info\n');
  process.stdout.write('  2. Edit .code-flow/specs/ — fill in your coding standards\n');
  process.stdout.write('  3. Run /project:cf-learn in Claude Code to auto-discover constraints\n');
  process.exit(0);
}

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

if (args.length === 1 && args[0] === 'init') {
  runInit();
}

if (args.length === 0) {
  fail('Error: missing command.');
}

if (args.includes('--path')) {
  fail('Error: --path is not supported; run init in the current directory.');
}

fail(`Error: unknown command "${args.join(' ')}".`);
