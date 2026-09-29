import { execFile } from "child_process";
import { join } from "path";
import { appendFileSync, mkdirSync } from "fs";

// Note: intentionally no `import { Plugin } from "@opencode/plugin"`.
// The server does not auto-provide that package for local plugins, and
// `Plugin.define` is only an identity wrapper — a plain default export
// with `id` + `setup` satisfies the v2 plugin schema dependency-free,
// so `code-flow init` works offline without npm install.

const SCRIPT_DIR = ".code-flow/scripts";
const STOP_CHECK_TIMEOUT = 35000;
const HOOK_TIMEOUT = 5000;

// Per-session queued feedback. Single map, append-only: idle/stop-check and
// post-check feedback accumulate here and are consumed by the next context
// hook. Never overwrite — a prompt hook arriving between idle and context
// must not drop queued stop-check feedback.
const sessionContext = new Map();

export function mergePending(existing, incoming) {
  if (!existing) return incoming;
  if (!incoming) return existing;
  return existing + "\n\n" + incoming;
}

function debugLog(projectRoot, msg) {
  if (process.env.CF_DEBUG !== "1") return;
  try {
    const dir = join(projectRoot, ".code-flow");
    mkdirSync(dir, { recursive: true });
    const ts = new Date().toISOString().replace("T", " ").slice(0, 19);
    appendFileSync(join(dir, ".debug.log"), `${ts} [opencode] ${msg}\n`);
  } catch {}
}

function pythonPath(projectRoot, script) {
  return join(projectRoot, SCRIPT_DIR, script);
}

function callHook(projectRoot, script, input, timeout = HOOK_TIMEOUT) {
  // Async child process: never block the plugin event thread. opencode's
  // idle event cannot interrupt a turn, so stop-check failures queue into
  // sessionContext for the next context hook (documented platform gap
  // vs. blocking Stop hooks).
  return new Promise((resolve) => {
    const child = execFile(
      "python3",
      [pythonPath(projectRoot, script)],
      { cwd: projectRoot, timeout, maxBuffer: 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          debugLog(projectRoot, `callHook ${script} failed: ${error.message || stderr}`);
          resolve(null);
          return;
        }
        const text = (stdout || "").trim();
        if (!text) {
          resolve(null);
          return;
        }
        try {
          resolve(JSON.parse(text));
        } catch (e) {
          debugLog(projectRoot, `callHook ${script} bad JSON: ${e.message}`);
          resolve(null);
        }
      }
    );
    if (input !== undefined && child.stdin) {
      child.stdin.write(JSON.stringify(input));
      child.stdin.end();
    }
  });
}

function queueFeedback(sessionID, text) {
  if (!sessionID || !text) return;
  sessionContext.set(sessionID, mergePending(sessionContext.get(sessionID), text));
}

function consumeFeedback(sessionID) {
  const pending = sessionContext.get(sessionID);
  if (pending) sessionContext.delete(sessionID);
  return pending;
}

function toolInputFilePath(input) {
  if (!input || typeof input !== "object") return "";
  const args = input;
  return args.filePath || args.file_path || args.path || "";
}

async function runStopCheck(projectRoot, sessionID) {
  const result = await callHook(projectRoot, "cf_stop_hook.py", { session_id: sessionID }, STOP_CHECK_TIMEOUT);
  if (result?.reason) {
    // idle 无法阻断，校验失败排队到下一轮 context hook
    queueFeedback(sessionID, result.reason);
    debugLog(projectRoot, `stop-check feedback queued`);
  }
}

async function registerPromptHook(ctx, projectRoot) {
  await ctx.session.hook("prompt", async (event) => {
    const promptText = event.prompt?.text || "";
    if (!promptText) return;
    debugLog(projectRoot, `prompt sid=${event.sessionID} prompt_len=${promptText.length}`);
    const result = await callHook(projectRoot, "cf_user_prompt_hook.py", {
      prompt: promptText,
      session_id: event.sessionID,
    });
    const additional = result?.hookSpecificOutput?.additionalContext;
    if (additional) {
      // Append, never overwrite: queued stop-check feedback survives.
      queueFeedback(event.sessionID, additional);
      debugLog(projectRoot, `hook matched — context ${additional.length} chars cached`);
    } else {
      debugLog(projectRoot, `hook returned no context`);
    }
  });
}

async function registerToolHook(ctx, projectRoot) {
  await ctx.tool.hook("execute.after", async (event) => {
    const tool = String(event.tool || "").toLowerCase();
    if (!["edit", "write", "multiedit", "patch"].includes(tool)) return;
    const filePath = toolInputFilePath(event.input);
    if (!filePath) return;
    const result = await callHook(projectRoot, "cf_post_hook.py", {
      tool_name: tool === "write" ? "Write" : "Edit",
      tool_input: { file_path: filePath },
      session_id: event.sessionID || "",
    });
    const additional = result?.hookSpecificOutput?.additionalContext;
    if (additional) {
      // 反馈排队，下一轮 context hook 注入（opencode 无法当轮插话）
      queueFeedback(event.sessionID, additional);
      debugLog(projectRoot, `post-check feedback queued ${additional.length} chars`);
    }
  });
}

async function registerContextHook(ctx) {
  await ctx.session.hook("context", (event) => {
    const pending = consumeFeedback(event.sessionID);
    if (pending) {
      event.system.push({ type: "text", text: pending });
      debugLog(ctx.location.directory, `context — injected ${pending.length} chars`);
    }
  });
}

function startEventSubscription(ctx, projectRoot) {
  const controller = new AbortController();
  void (async () => {
    try {
      for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
        if (!event || typeof event.type !== "string") continue;
        if (event.type === "session.created") {
          const sid = event.data?.sessionID || "";
          debugLog(projectRoot, `session.created sid=${sid}`);
          if (sid) sessionContext.delete(sid);
        } else if (event.type === "session.idle") {
          const sid = event.data?.sessionID || "";
          if (sid) await runStopCheck(projectRoot, sid);
        }
      }
    } catch (err) {
      if (err?.name !== "AbortError") {
        debugLog(projectRoot, `event subscription ended: ${err?.message || err}`);
      }
    }
  })();
  return () => controller.abort();
}

const CodeFlowPlugin = {
  id: "code-flow",
  async setup(ctx) {
    const projectRoot = ctx.location.directory;
    await registerPromptHook(ctx, projectRoot);
    await registerToolHook(ctx, projectRoot);
    await registerContextHook(ctx);
    const stopSubscription = startEventSubscription(ctx, projectRoot);
    return () => stopSubscription();
  },
};

export default CodeFlowPlugin;
