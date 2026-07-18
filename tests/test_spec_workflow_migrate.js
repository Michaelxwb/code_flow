"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const migrate = require("../src/migrate/spec-workflow");

const SPEC = `---
id: app-rules
description: App rules
stages: [design, plan, code]
enforcement: required
verifiers:
  - rule: RULE-app-001
    type: test
    config:
      argv: [python3, -m, pytest]
---
# App
## Rules
- [RULE-app-001] Keep compatible.
`;

function project() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cf-migrate-"));
  fs.mkdirSync(path.join(root, ".code-flow/specs/app"), { recursive: true });
  fs.mkdirSync(path.join(root, ".code-flow/tasks/2026-07-18"), { recursive: true });
  fs.writeFileSync(path.join(root, ".code-flow/.version"), "0.5.2");
  fs.writeFileSync(path.join(root, ".code-flow/config.yml"), "path_mapping:\n  app:\n    patterns: ['src/*']\n    specs:\n      - path: app/rules.md\n");
  fs.writeFileSync(path.join(root, ".code-flow/specs/app/rules.md"), SPEC);
  fs.writeFileSync(path.join(root, ".code-flow/tasks/2026-07-18/demo.md"), "# Tasks\n");
  return root;
}

function snapshot(root) {
  const result = {};
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(full);
      else result[path.relative(root, full)] = crypto.createHash("sha256").update(fs.readFileSync(full)).digest("hex");
    }
  }
  visit(root);
  return result;
}

test("B-08 dry-run is a single in-memory preview with zero writes", () => {
  const root = project();
  const before = snapshot(root);
  const result = migrate.preview(root);
  assert.equal(result.ready, true);
  assert.equal(result.target_package_version, "0.6.0");
  assert.deepEqual(snapshot(root), before);
  assert.equal(fs.existsSync(path.join(root, ".code-flow/migrations")), false);
});

test("prepare creates bound plan, byte backup, empty staging and journal", () => {
  const root = project();
  const before = snapshot(root);
  const result = migrate.prepare(root);
  assert.equal(result.status, "prepared");
  const workspace = result.workspace;
  const plan = JSON.parse(fs.readFileSync(path.join(workspace, "migration-plan.json"), "utf8"));
  const journal = JSON.parse(fs.readFileSync(path.join(workspace, "journal.json"), "utf8"));
  assert.equal(plan.project_root, fs.realpathSync(root));
  assert.deepEqual(plan.source_hashes, before);
  assert.equal(journal.status, "prepared");
  assert.deepEqual(fs.readdirSync(path.join(workspace, "staging")), []);
  for (const relative of Object.keys(before)) {
    assert.equal(fs.readFileSync(path.join(workspace, "backup", relative)).equals(fs.readFileSync(path.join(root, relative))), true);
  }
});

test("S-12 apply is idempotent and writes version last", () => {
  const root = project();
  const prepared = migrate.prepare(root);
  const applied = migrate.apply(prepared.plan);
  assert.equal(applied.status, "committed");
  assert.equal(fs.readFileSync(path.join(root, ".code-flow/.version"), "utf8"), "0.6.0");
  const beforeSecond = snapshot(root);
  const second = migrate.apply(prepared.plan);
  assert.equal(second.status, "already_migrated");
  assert.deepEqual(snapshot(root), beforeSecond);
});

test("E-08 injected rename failure restores all original bytes", () => {
  for (const failAfter of [0, 3]) {
    const root = project();
    const original = snapshot(root);
    const prepared = migrate.prepare(root);
    const result = migrate.apply(prepared.plan, { failAfter });
    assert.equal(result.status, "rolled_back");
    const restored = snapshot(root);
    for (const [relative, digest] of Object.entries(original)) assert.equal(restored[relative], digest);
    assert.notEqual(fs.readFileSync(path.join(root, ".code-flow/.version"), "utf8"), "0.6.0");
  }
});

test("B-05 interruption before version is completed from proven target hashes", () => {
  const root = project();
  const prepared = migrate.prepare(root);
  const interrupted = migrate.apply(prepared.plan, { interruptBeforeVersion: true });
  assert.equal(interrupted.status, "committing");
  assert.equal(fs.readFileSync(path.join(root, ".code-flow/.version"), "utf8"), "0.5.2");
  const recovered = migrate.apply(prepared.plan);
  assert.equal(recovered.status, "committed");
  assert.equal(fs.readFileSync(path.join(root, ".code-flow/.version"), "utf8"), "0.6.0");
});

test("EXDEV fails closed and rolls back without copy-delete commit fallback", () => {
  const root = project();
  const original = snapshot(root);
  const prepared = migrate.prepare(root);
  const result = migrate.apply(prepared.plan, { exdevAfter: 1 });
  assert.equal(result.status, "rolled_back");
  const restored = snapshot(root);
  for (const [relative, digest] of Object.entries(original)) assert.equal(restored[relative], digest);
});
