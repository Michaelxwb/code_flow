// OpenCode v2 插件回归测试。
// Run via `node tests/test_opencode_plugin.js`.

import assert from "node:assert";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PLUGIN = path.resolve(import.meta.dirname, "..", "src/adapters/opencode/plugins/code-flow/index.js");
const mod = await import(pathToFileURL(PLUGIN).href);
const { mergePending, createSessionRegistry } = mod;
const plugin = mod.default;

// 反馈合并：append-only，永不覆盖排队中的 stop-check 反馈
assert.equal(mergePending(undefined, "b"), "b");
assert.equal(mergePending("a", undefined), "a");
assert.equal(mergePending("stop-feedback", "prompt-context"), "stop-feedback\n\nprompt-context");

// v2 形态：默认导出 { id, setup }，不再是 v1 的具名 CodeFlow 工厂
assert.ok(plugin && typeof plugin === "object", "必须默认导出插件定义对象");
assert.equal(plugin.id, "code-flow");
assert.equal(plugin.setup.constructor.name, "AsyncFunction", "setup 必须异步");
assert.ok(!("CodeFlow" in mod), "不得残留 v1 具名导出 CodeFlow");

// setup 注册 v2 hooks：session.prompt + session.context + tool.execute.after，
// 并订阅事件流（session.created / session.idle 经 event.subscribe 处理）
const recorded = { session: [], tool: [] };
const callbacks = {};
const mockCtx = {
  location: { directory: import.meta.dirname },
  session: {
    hook: async (name, cb) => {
      recorded.session.push(name);
      callbacks[`session:${name}`] = cb;
      return { dispose: async () => {} };
    },
  },
  tool: {
    hook: async (name, cb) => {
      recorded.tool.push(name);
      callbacks[`tool:${name}`] = cb;
      return { dispose: async () => {} };
    },
  },
  event: {
    subscribe: (_opts) => (async function* () {})(),
  },
};
const cleanup = await plugin.setup(mockCtx);
assert.deepEqual(recorded.session, ["prompt", "context"]);
assert.deepEqual(recorded.tool, ["execute.after"]);
assert.equal(typeof cleanup, "function", "setup 必须返回清理函数");

// 空 prompt 直接返回，不触发 python 子进程
await callbacks["session:prompt"]({ prompt: { text: "" }, sessionID: "s1" });
// 无排队反馈时 context hook 不注入
const system = [];
await callbacks["session:context"]({ sessionID: "s1", system });
assert.deepEqual(system, []);
cleanup();

// 子会话过滤：子 agent/worktree 会话的 idle 不得触发主工作区 stop-check
const registry = createSessionRegistry();
registry.observe({ type: "session.created", data: { sessionID: "main" } });
assert.equal(registry.observe({ type: "session.idle", data: { sessionID: "main" } }).child, false);
registry.observe({ type: "session.created", data: { sessionID: "child", parentID: "main" } });
assert.equal(registry.observe({ type: "session.idle", data: { sessionID: "child" } }).child, true);
assert.equal(registry.observe({ type: "session.idle", data: {} }), null);
assert.equal(registry.observe({ type: "session.updated", data: { sessionID: "main" } }), null);

// 源码级断言：无同步阻塞调用、无 v1 hook 键残留
const { readFileSync } = await import("node:fs");
const source = readFileSync(PLUGIN, "utf-8");
assert.ok(!source.includes("spawnSync"), "不得残留 spawnSync");
assert.ok(source.includes("execFile"), "必须使用异步 execFile");
for (const legacy of ["chat.message", "tool.execute.after", "experimental.chat.system.transform", "CodeFlow"]) {
  if (legacy === "tool.execute.after") continue; // v2 tool hook 同名，检查其注册形式
  assert.ok(!source.includes(`"${legacy}"`), `不得残留 v1 键 ${legacy}`);
}
assert.ok(source.includes('ctx.session.hook("prompt"'), "必须注册 session prompt hook");
assert.ok(source.includes('ctx.session.hook("context"'), "必须注册 session context hook");
assert.ok(source.includes('ctx.tool.hook("execute.after"'), "必须注册 tool execute.after hook");
assert.ok(source.includes("ctx.event.subscribe"), "必须订阅事件流");
assert.ok(source.includes('{ type: "text", text:'), "system 注入必须使用 v2 SystemPart 形态");

console.log("All opencode plugin tests passed.");
