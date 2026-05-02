import { spawnSync } from "child_process";
import { join } from "path";
import { appendFileSync, mkdirSync } from "fs";

const SCRIPT_DIR = ".code-flow/scripts";

// Per-session cache of spec context to inject into system prompt
const sessionContext = new Map();

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

function callHook(projectRoot, script, input) {
  try {
    const proc = spawnSync("python3", [pythonPath(projectRoot, script)], {
      cwd: projectRoot,
      input: JSON.stringify(input),
      encoding: "utf-8",
      timeout: 5000,
      maxBuffer: 1024 * 1024,
    });
    if (proc.error || proc.status !== 0) {
      debugLog(projectRoot, `callHook ${script} failed: ${proc.error || proc.stderr}`);
      return null;
    }
    const stdout = (proc.stdout || "").trim();
    if (!stdout) return null;
    return JSON.parse(stdout);
  } catch (e) {
    debugLog(projectRoot, `callHook ${script} exception: ${e.message}`);
    return null;
  }
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
        callHook(projectRoot, "cf_session_hook.py", { session_id: sid });
      }
    },

    "chat.message": async (input, output) => {
      const promptText = extractPromptText(output);
      if (!promptText) return;

      debugLog(projectRoot, `chat.message sid=${input.sessionID} prompt_len=${promptText.length}`);

      const result = callHook(projectRoot, "cf_user_prompt_hook.py", {
        prompt: promptText,
        session_id: input.sessionID,
      });

      if (result?.hookSpecificOutput?.additionalContext) {
        const ctxLen = result.hookSpecificOutput.additionalContext.length;
        debugLog(projectRoot, `hook matched — context ${ctxLen} chars cached`);
        sessionContext.set(
          input.sessionID,
          result.hookSpecificOutput.additionalContext
        );
      } else {
        debugLog(projectRoot, `hook returned no context`);
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
