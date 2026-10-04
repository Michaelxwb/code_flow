// Native v2 callbacks exercise the installed Python runtime, without an LLM.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import plugin, { mergePending } from "../src/adapters/opencode/plugins/code-flow/index.js";

const ROOT = path.resolve(import.meta.dirname, "..");
const directory = mkdtempSync(path.join(tmpdir(), "cf-opencode-native-"));
const errors = [];
const originalError = console.error;
console.error = message => errors.push(message);

function install(root) {
  mkdirSync(root, { recursive: true });
  execFileSync(process.execPath, [path.join(ROOT, "src/cli.js"), "init", "--platform=opencode"], { cwd: root });
  rmSync(path.join(root, ".code-flow/specs"), { recursive: true });
  mkdirSync(path.join(root, "src"), { recursive: true });
  mkdirSync(path.join(root, ".code-flow/specs/scripts"), { recursive: true });
  writeFileSync(path.join(root, ".code-flow/config.yml"), `spec_workflow:\n  schema_version: 1\nquality_loop:\n  enabled: true\n  code_extensions: [".py"]\npath_mapping:\n  scripts:\n    patterns: ["src/*.py"]\n    specs:\n      - path: scripts/rules.md\n        tags: [python]\n        tier: 1\n`);
  writeFileSync(path.join(root, ".code-flow/specs/scripts/rules.md"), `---\nid: python-rules\ndescription: Native Python rules\nstages: [code]\nenforcement: required\nchecks:\n  - id: no-debug\n    type: regex\n    pattern: 'print\\('\n    files: '*.py'\n    message: Remove debug printing\nverifiers:\n  - rule: RULE-python-001\n    type: regex\n    config:\n      pattern: SAFE\n---\n## Rules\n- [RULE-python-001] Keep SAFE.\n`);
  writeFileSync(path.join(root, "src/a.py"), "SAFE\n");
}

function events(root, name) {
  const file = path.join(root, ".code-flow/.session-log.jsonl");
  try { return readFileSync(file, "utf8").trim().split("\n").map(JSON.parse).filter(item => item.event === name); }
  catch (error) { if (error.code === "ENOENT") return []; throw error; }
}

async function harness(root, sessions = {}, subscriptionError = null) {
  const hooks = {}, messages = [];
  let wake;
  const signalBox = {};
  const ctx = {
    location: { directory: root },
    session: {
      get: async ({ sessionID }) => sessions[sessionID] || { location: { directory: root } },
      hook: async (name, callback) => { hooks[`session:${name}`] = callback; },
    },
    tool: { hook: async (name, callback) => { hooks[`tool:${name}`] = callback; } },
    event: { subscribe: ({ signal }) => (async function* () {
      signalBox.signal = signal;
      if (subscriptionError) throw subscriptionError;
      signal.addEventListener("abort", () => wake?.(), { once: true });
      while (!signal.aborted) {
        if (!messages.length) await new Promise(resolve => { wake = resolve; });
        while (messages.length && !signal.aborted) {
          const { event, done } = messages.shift();
          yield event;
          done();
        }
      }
    })() },
  };
  const cleanup = await plugin.setup(ctx);
  return { hooks, cleanup, signalBox, send: event => new Promise(done => { messages.push({ event, done }); wake?.(); }) };
}

async function context(harness, sessionID) {
  const event = { sessionID, system: [] };
  await harness.hooks["session:context"](event);
  return event.system.map(part => part.text).join("\n");
}

try {
  assert.equal(plugin.id, "code-flow");
  assert.equal(mergePending("stop", "prompt"), "stop\n\nprompt");
  assert.ok(!("server" in plugin));
  install(directory);
  const h = await harness(directory);
  assert.deepEqual(Object.keys(h.hooks), ["session:prompt", "session:context", "tool:execute.before", "tool:execute.after"]);
  await h.hooks["session:prompt"]({ sessionID: "main", prompt: { text: "review src/a.py" } });
  const edit = { sessionID: "main", tool: "edit", id: "call-1", input: { path: "src/a.py", oldString: "SAFE", newString: "print('debug')" } };
  assert.equal(await h.hooks["tool:execute.before"](edit), undefined);
  writeFileSync(path.join(directory, "src/a.py"), "print('debug')\n");
  await h.hooks["tool:execute.after"]({ ...edit, status: "completed", result: { content: "native result" } });
  const feedback = await context(h, "main");
  assert.ok(feedback.includes("RULE-python-001") && feedback.includes("Remove debug printing"));
  assert.equal(events(directory, "edit").length, 1);
  assert.equal(await context(h, "other"), "");

  await h.hooks["tool:execute.after"]({ ...edit, status: "error", error: { message: "native edit failed" } });
  assert.equal(events(directory, "edit").length, 1);
  assert.ok(events(directory, "degrade").some(item => item.data.component === "opencode_tool"));
  assert.equal(await context(h, "main"), "");

  await h.hooks["session:prompt"]({ sessionID: "deleted", prompt: { text: "review src/a.py" } });
  await h.send({ type: "session.deleted", data: { sessionID: "deleted" } });
  assert.equal(await context(h, "deleted"), "");
  assert.equal(await context(h, "main"), "");

  const faulty = await harness(directory, {}, new Error("subscription unavailable"));
  assert.match(await context(faulty, "fault-first"), /subscription unavailable/);
  assert.equal(await context(faulty, "fault-second"), "");

  const patch = { sessionID: "patch-session", tool: "patch", id: "call-2", input: { patchText:
    "*** Begin Patch\n*** Update File: src/a.py\n*** Move to: src/moved.py\n@@\n-old\n+SAFE\n*** Add File: src/b.py\n+SAFE\n*** Delete File: src/old.py\n*** End Patch" } };
  await h.hooks["tool:execute.before"](patch);
  rmSync(path.join(directory, "src/a.py"));
  writeFileSync(path.join(directory, "src/moved.py"), "SAFE\n");
  writeFileSync(path.join(directory, "src/b.py"), "SAFE\n");
  await h.hooks["tool:execute.after"]({ ...patch, status: "completed", result: { content: "native patch result" } });
  assert.deepEqual(events(directory, "edit").filter(item => item.sid === "patch-session").map(item => item.data.file).sort(),
    ["src/a.py", "src/b.py", "src/moved.py", "src/old.py"]);

  const before = events(directory, "edit_intent").length;
  await assert.rejects(h.hooks["tool:execute.before"]({ ...patch, input: { patchText:
    "*** Begin Patch\n*** Add File: src/c.py\n+SAFE\n*** Delete File: ../outside.py\n*** End Patch" } }), /outside project/);
  assert.equal(events(directory, "edit_intent").length, before);
  assert.ok((await context(h, "patch-session")).includes("outside project"));

  const worktree = path.join(directory, ".code-flow/worktrees/native/task");
  install(worktree);
  const local = await harness(directory, { child: { parentID: "main", location: { directory: worktree } } });
  await local.hooks["tool:execute.before"]({ ...edit, sessionID: "child" });
  assert.equal(events(worktree, "edit_intent").length, 1);
  assert.ok(!events(directory, "edit_intent").some(item => item.sid === "child"));
  const isolated = await harness(worktree);
  assert.equal(await context(isolated, "child"), "");
  assert.ok((await context(local, "child")).includes("RULE-python-001"));
  const nested = await harness(directory, { nested: { location: { directory: path.join(directory, "src") } } });
  await nested.hooks["tool:execute.before"]({ ...edit, sessionID: "nested", input: { path: "b.py" } });
  assert.ok(events(directory, "edit_intent").some(item => item.sid === "nested" && item.data.file === "src/b.py"));
  const pendingEdit = nested.hooks["tool:execute.before"]({ ...edit, sessionID: "concurrent", input: { path: "src/b.py" } });
  const concurrentContext = context(nested, "concurrent");
  await pendingEdit;
  assert.ok((await concurrentContext).includes("RULE-python-001"));
  const own = await harness(worktree, {
    child: { parentID: "main", location: { directory: worktree } }, main: { location: { directory } },
  });
  writeFileSync(path.join(worktree, ".code-flow/.active-task.json"), "{}");
  await own.send({ type: "session.idle", data: { sessionID: "child" } });
  assert.ok((await context(own, "child")).includes("SPEC_WORKFLOW_BLOCKED"));

  writeFileSync(path.join(directory, ".code-flow/.active-task.json"), "{}");
  for (const [hook, event] of [
    ["tool:execute.before", { ...edit, sessionID: "blocked-edit" }],
    ["session:prompt", { sessionID: "blocked-prompt", prompt: { text: "review src/a.py" } }],
  ]) {
    await assert.rejects(h.hooks[hook](event), /SPEC_WORKFLOW_BLOCKED/);
    assert.equal((await context(h, event.sessionID)).match(/SPEC_WORKFLOW_BLOCKED/g)?.length, 1);
    assert.equal(await context(h, event.sessionID), "");
  }
  await h.send({ type: "session.idle", data: { sessionID: "main" } });
  assert.ok((await context(h, "main")).includes("SPEC_WORKFLOW_BLOCKED"));
  const child = await harness(directory, { child: { parentID: "main", location: { directory } } });
  await child.send({ type: "session.idle", data: { sessionID: "child" } });
  assert.equal(await context(child, "child"), "");
  rmSync(path.join(directory, ".code-flow/.active-task.json"));

  // Isolate the plugin's consumption of an advisory scope-expansion RPC result.
  // Python coverage separately exercises the shared service and native dispatch.
  const entry = path.join(directory, ".code-flow/scripts/cf_opencode_event.py");
  const nativeEntry = readFileSync(entry, "utf8");
  writeFileSync(entry, 'import json\nprint(json.dumps({"context": "未绑定 required Spec: refresh Context / Plan", "blocked": False}))\n');
  await h.hooks["tool:execute.before"]({ ...edit, sessionID: "expansion" });
  assert.match(await context(h, "expansion"), /refresh Context \/ Plan/);
  assert.equal(await context(h, "expansion"), "");
  writeFileSync(entry, nativeEntry);

  const service = path.join(directory, ".code-flow/scripts/cf_edit_service.py");
  writeFileSync(service, readFileSync(service, "utf8") + "\n# runtime drift\n");
  await h.send({ type: "session.idle", data: { sessionID: "idle-error" } });
  assert.equal((await context(h, "idle-error")).match(/drifted/g)?.length, 1);
  assert.equal(await context(h, "idle-error"), "");
  await assert.rejects(h.hooks["tool:execute.before"](edit), /drifted/);
  await h.hooks["tool:execute.after"]({ ...edit, status: "completed", result: { content: "unchanged" } });
  assert.ok((await context(h, "main")).includes("drifted"));
  assert.ok(errors.some(message => message.includes("drifted")));
  writeFileSync(path.join(directory, ".code-flow/scripts/cf_opencode_event.py"), "import sys\nsys.stdout.write('invalid JSON')\n");
  await h.hooks["tool:execute.after"]({ ...edit, status: "completed", result: { content: "unchanged" } });
  assert.ok((await context(h, "main")).includes("Unexpected token"));
  for (const instance of [h, local, isolated, child, nested, own, faulty]) { instance.cleanup(); assert.ok(instance.signalBox.signal.aborted); }
  console.log("OpenCode v2 native callback/runtime integration tests passed.");
} finally {
  console.error = originalError;
  rmSync(directory, { recursive: true, force: true });
}
