// [TASK-011] opencode 插件异步化与反馈合并回归测试。
// Run via `node tests/test_opencode_plugin.js`. ESM: package.json 无 type 字段时
// 用 .mjs 包装加载？本文件为 .js，仓库已有 node 单测先例，直接导入目标模块。

import assert from "node:assert";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PLUGIN = path.resolve(import.meta.dirname, "..", "src/adapters/opencode/plugins/code-flow/index.js");
const { CodeFlow, mergePending } = await import(pathToFileURL(PLUGIN).href);

// 反馈合并：append-only，永不覆盖排队中的 stop-check 反馈
assert.equal(mergePending(undefined, "b"), "b");
assert.equal(mergePending("a", undefined), "a");
assert.equal(mergePending("stop-feedback", "prompt-context"), "stop-feedback\n\nprompt-context");

// 异步化：工厂与全部 handler 必须为 AsyncFunction（无 spawnSync 阻塞）
assert.equal(CodeFlow.constructor.name, "AsyncFunction", "CodeFlow 必须异步");
const api = await CodeFlow({ directory: import.meta.dirname });
for (const key of ["event", "chat.message", "tool.execute.after", "experimental.chat.system.transform"]) {
  const handler = key === "event" ? api.event : api[key];
  assert.equal(handler.constructor.name, "AsyncFunction", `${key} 必须异步`);
}
// 无同步阻塞调用残留
const { readFileSync } = await import("node:fs");
const source = readFileSync(PLUGIN, "utf-8");
assert.ok(!source.includes("spawnSync"), "不得残留 spawnSync");
assert.ok(source.includes("execFile"), "必须使用异步 execFile");

console.log("All opencode plugin tests passed.");
