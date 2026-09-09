import { execFile } from "child_process";
import { join } from "path";
import { appendFileSync, mkdirSync } from "fs";

const SCRIPT_DIR = ".code-flow/scripts";

// Per-session queued feedback. Single map, append-only: idle/stop-check and
// post-check feedback accumulate here and are consumed by the next
// system.transform. Never overwrite — chat.message arriving between idle and
// transform must not drop queued stop-check feedback.
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

function callHook(projectRoot, script, input, timeout = 5000) {
  // Async child process: never block the plugin event thread. opencode's
  // idle event cannot interrupt a turn, so stop-check failures queue into
  // sessionContext for the next system.transform (documented platform gap
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

function extractPromptText(output) {
  if (!output.parts) return "";
  return output.parts
    .filter((p) => p.type === "text" && !p.synthetic && !p.ignored)
    .map((p) => p.text)
    .join("\n");
}

export const CodeFlow = async (ctx) => {
  const projectRoot = ctx.directory;

  return {
    event: async (input) => {
      if (input.event?.type === "session.created") {
        const sid = input.event?.properties?.info?.id || "";
        debugLog(projectRoot, `session.created sid=${sid}`);
        if (sid) sessionContext.delete(sid);
      }
      if (input.event?.type === "session.idle") {
        const sid =
          input.event?.properties?.sessionID ||
          input.event?.properties?.info?.id || "";
        const result = await callHook(projectRoot, "cf_stop_hook.py", { session_id: sid }, 35000);
        if (result?.reason) {
          // idle 无法阻断，校验失败排队到下一轮 system prompt
          sessionContext.set(sid, mergePending(sessionContext.get(sid), result.reason));
          debugLog(projectRoot, `stop-check feedback queued`);
        }
      }
    },

    "chat.message": async (input, output) => {
      const promptText = extractPromptText(output);
      if (!promptText) return;

      debugLog(projectRoot, `chat.message sid=${input.sessionID} prompt_len=${promptText.length}`);

      const result = await callHook(projectRoot, "cf_user_prompt_hook.py", {
        prompt: promptText,
        session_id: input.sessionID,
      });

      if (result?.hookSpecificOutput?.additionalContext) {
        const ctxLen = result.hookSpecificOutput.additionalContext.length;
        debugLog(projectRoot, `hook matched — context ${ctxLen} chars cached`);
        // Append, never overwrite: queued stop-check feedback survives.
        sessionContext.set(
          input.sessionID,
          mergePending(sessionContext.get(input.sessionID), result.hookSpecificOutput.additionalContext)
        );
      } else {
        debugLog(projectRoot, `hook returned no context`);
      }
    },

    "tool.execute.after": async (input, output) => {
      const tool = String(input?.tool || "").toLowerCase();
      if (!["edit", "write", "multiedit", "patch"].includes(tool)) return;
      const args = output?.args || input?.args || {};
      const filePath = args.filePath || args.file_path || args.path;
      if (!filePath) return;
      const result = await callHook(projectRoot, "cf_post_hook.py", {
        tool_name: tool === "write" ? "Write" : "Edit",
        tool_input: { file_path: filePath },
        session_id: input?.sessionID || "",
      });
      const ctx = result?.hookSpecificOutput?.additionalContext;
      if (ctx) {
        // 反馈排队，下一轮 system.transform 注入（opencode 无法当轮插话）
        const sid = input?.sessionID || "";
        sessionContext.set(sid, mergePending(sessionContext.get(sid), ctx));
        debugLog(projectRoot, `post-check feedback queued ${ctx.length} chars`);
      }
    },

    "experimental.chat.system.transform": async (input, output) => {
      const ctx = sessionContext.get(input.sessionID);
      if (ctx) {
        output.system.push(ctx);
        debugLog(projectRoot, `system.transform — injected ${ctx.length} chars, system now ${output.system.length} parts`);
        sessionContext.delete(input.sessionID);
      }
    },
  };
};
