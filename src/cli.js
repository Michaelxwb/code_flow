#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const usage = [
  'Usage: code-flow init',
  '       code-flow --help'
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

function runInit() {
  ensurePython3();

  const cwd = process.cwd();
  const baseDir = __dirname;
  const coreDir = path.join(baseDir, 'core');
  const adaptersDir = path.join(baseDir, 'adapters');

  copyDirRecursive(path.join(coreDir, 'code-flow'), path.join(cwd, '.code-flow'));
  copyFileIfMissing(path.join(adaptersDir, 'claude', 'CLAUDE.md'), path.join(cwd, 'CLAUDE.md'));
  copyDirRecursive(path.join(adaptersDir, 'claude'), path.join(cwd, '.claude'));

  const result = spawnSync(
    'python3',
    ['.code-flow/scripts/cf_init.py'],
    { stdio: 'inherit', cwd }
  );

  if (result.error) {
    process.stderr.write(`Error: ${result.error.message}\n`);
    process.exit(1);
  }

  process.exit(result.status ?? 0);
}

const args = process.argv.slice(2);

if (args.length === 1 && args[0] === '--help') {
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
