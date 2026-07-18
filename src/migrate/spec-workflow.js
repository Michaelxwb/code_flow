"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PREFLIGHT = path.join(__dirname, "../core/code-flow/scripts/cf_spec_migrate.py");

function walkFiles(root, directory = root) {
  const files = [];
  if (!fs.existsSync(directory)) return files;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    const relative = path.relative(root, full);
    if (entry.isDirectory() && relative === path.join(".code-flow", "migrations")) continue;
    if (entry.isDirectory()) files.push(...walkFiles(root, full));
    else files.push(relative);
  }
  return files.sort();
}

function migrationFiles(root) {
  const entries = [".code-flow", ".claude", ".codex", ".costrict", ".opencode", ".agents", "AGENTS.md", "CLAUDE.md"];
  const files = [];
  for (const entry of entries) {
    const target = path.join(root, entry);
    if (!fs.existsSync(target)) continue;
    if (fs.statSync(target).isDirectory()) files.push(...walkFiles(root, target));
    else files.push(entry);
  }
  return [...new Set(files)].sort();
}

function hash(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function sourceHashes(root) {
  const result = {};
  for (const relative of migrationFiles(root)) {
    result[relative] = hash(fs.readFileSync(path.join(root, relative)));
  }
  return result;
}

function pythonCommand() {
  return process.env.PYTHON || "python3";
}

function preview(root) {
  const project = fs.realpathSync(root);
  const result = childProcess.spawnSync(
    pythonCommand(), [PREFLIGHT, "preflight", "--root", project, "--json"],
    { encoding: "utf8", shell: false }
  );
  if (result.status !== 0) throw new Error(result.stderr || result.stdout || "preflight failed");
  return JSON.parse(result.stdout);
}

function migrationId(root, hashes) {
  const seed = `${root}\0${JSON.stringify(hashes)}\0${Date.now()}`;
  return `spec-workflow-${hash(seed).slice(0, 12)}`;
}

function copyBackup(root, backup, hashes) {
  for (const relative of Object.keys(hashes)) {
    const target = path.join(backup, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(root, relative), target);
  }
}

function writeJson(target, value) {
  fs.writeFileSync(target, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function prepare(root) {
  const project = fs.realpathSync(root);
  const plan = preview(project);
  const hashes = sourceHashes(project);
  const id = migrationId(project, hashes);
  const workspace = path.join(project, ".code-flow", "migrations", id);
  const backup = path.join(workspace, "backup");
  const staging = path.join(workspace, "staging");
  fs.mkdirSync(backup, { recursive: true });
  fs.mkdirSync(staging, { recursive: true });
  copyBackup(project, backup, hashes);
  const preparedPlan = { ...plan, migration_id: id, project_root: project, source_hashes: hashes };
  const status = plan.unresolved.length ? "prepared_blocked" : "prepared";
  writeJson(path.join(workspace, "migration-plan.json"), preparedPlan);
  writeJson(path.join(workspace, "journal.json"), { version: 1, migration_id: id, status, operations: [] });
  return { migration_id: id, status, workspace, plan: path.join(workspace, "migration-plan.json") };
}

function readJson(target) {
  return JSON.parse(fs.readFileSync(target, "utf8"));
}

function journalPaths(planPath) {
  const workspace = path.dirname(planPath);
  return { workspace, journal: path.join(workspace, "journal.json"), staging: path.join(workspace, "staging"), backup: path.join(workspace, "backup") };
}

function sameHashes(first, second) {
  return JSON.stringify(first) === JSON.stringify(second);
}

function runStaging(planPath, locations) {
  const result = childProcess.spawnSync(
    pythonCommand(), [PREFLIGHT, "stage", "--plan", planPath, "--staging", locations.staging, "--json"],
    { encoding: "utf8", shell: false }
  );
  if (result.status !== 0) throw new Error(result.stdout || result.stderr || "staging failed");
  return JSON.parse(result.stdout);
}

function verifyStaging(staging, manifest) {
  for (const item of manifest.targets) {
    const target = path.join(staging, item.path);
    if (!fs.existsSync(target) || hash(fs.readFileSync(target)) !== item.sha256) {
      throw new Error(`staging hash mismatch: ${item.path}`);
    }
  }
}

function persistJournal(target, journal, status) {
  journal.status = status;
  writeJson(target, journal);
}

function targetEntries(manifest) {
  return manifest.targets.filter((item) => item.path !== ".code-flow/.version");
}

function commitEntry(project, staging, item, journal, journalPath) {
  const source = path.join(staging, item.path);
  const target = path.join(project, item.path);
  journal.operations.push({ path: item.path, status: "renaming" });
  writeJson(journalPath, journal);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
  fs.renameSync(source, target);
  journal.operations[journal.operations.length - 1].status = "committed";
  writeJson(journalPath, journal);
}

function obsoletePaths(plan, manifest) {
  const targets = new Set(manifest.targets.map((item) => item.path));
  return Object.keys(plan.source_hashes).filter((item) => item.startsWith(".code-flow/") && item !== ".code-flow/.version" && !targets.has(item));
}

function removeObsolete(project, paths) {
  for (const relative of paths) fs.rmSync(path.join(project, relative), { recursive: true, force: true });
}

function restoreBackup(plan, locations, manifest) {
  for (const item of manifest.targets || []) {
    if (item.path !== ".code-flow/.version") fs.rmSync(path.join(plan.project_root, item.path), { recursive: true, force: true });
  }
  for (const relative of Object.keys(plan.source_hashes)) {
    const source = path.join(locations.backup, relative);
    const target = path.join(plan.project_root, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(source, target);
  }
}

function rollback(planPath, error = "requested") {
  const plan = readJson(planPath);
  const locations = journalPaths(planPath);
  const journal = readJson(locations.journal);
  try {
    restoreBackup(plan, locations, journal.manifest || { targets: [] });
    journal.error = String(error);
    persistJournal(locations.journal, journal, "rolled_back");
    return { status: "rolled_back", migration_id: plan.migration_id };
  } catch (restoreError) {
    journal.error = String(restoreError);
    persistJournal(locations.journal, journal, "recovery_required");
    return { status: "recovery_required", migration_id: plan.migration_id };
  }
}

function targetsMatch(project, manifest) {
  return targetEntries(manifest).every((item) => {
    const target = path.join(project, item.path);
    return fs.existsSync(target) && hash(fs.readFileSync(target)) === item.sha256;
  });
}

function finishVersion(plan, journal, journalPath) {
  fs.writeFileSync(path.join(plan.project_root, ".code-flow/.version"), "0.6.0", "utf8");
  persistJournal(journalPath, journal, "committed");
  return { status: "committed", migration_id: plan.migration_id };
}

function recoverCommitting(plan, journal, locations, options) {
  if (!targetsMatch(plan.project_root, journal.manifest)) return rollback(path.join(locations.workspace, "migration-plan.json"), "target hash mismatch");
  if (options.interruptBeforeVersion) return { status: "committing", migration_id: plan.migration_id };
  return finishVersion(plan, journal, locations.journal);
}

function apply(planPath, options = {}) {
  const plan = readJson(planPath);
  const locations = journalPaths(planPath);
  const versionPath = path.join(plan.project_root, ".code-flow/.version");
  if (fs.existsSync(versionPath) && fs.readFileSync(versionPath, "utf8").trim() === "0.6.0") return { status: "already_migrated", migration_id: plan.migration_id };
  const journal = readJson(locations.journal);
  if (journal.status === "committing") return recoverCommitting(plan, journal, locations, options);
  if (plan.unresolved.length) throw new Error("migration plan has unresolved items");
  if (!sameHashes(sourceHashes(plan.project_root), plan.source_hashes)) throw new Error("source hash drift");
  try {
    const manifest = runStaging(planPath, locations);
    verifyStaging(locations.staging, manifest);
    journal.manifest = manifest;
    persistJournal(locations.journal, journal, "committing");
    let completed = 0;
    for (const item of targetEntries(manifest)) {
      if (options.failAfter === completed) throw new Error(`injected rename failure ${completed}`);
      if (options.exdevAfter === completed) {
        const exdev = new Error("injected EXDEV");
        exdev.code = "EXDEV";
        throw exdev;
      }
      commitEntry(plan.project_root, locations.staging, item, journal, locations.journal);
      completed += 1;
    }
    removeObsolete(plan.project_root, obsoletePaths(plan, manifest));
    removeObsolete(plan.project_root, manifest.deletions || []);
    if (options.interruptBeforeVersion) return { status: "committing", migration_id: plan.migration_id };
    return finishVersion(plan, journal, locations.journal);
  } catch (error) {
    return rollback(planPath, error);
  }
}

module.exports = { apply, preview, prepare, rollback, sourceHashes, walkFiles };
