import { execFile } from "node:child_process";
import { join, isAbsolute, resolve, dirname } from "node:path";
import { existsSync } from "node:fs";

const HOOK_TIMEOUT = 5000;
const IDLE_TIMEOUT = 35000;

function runtimeScript(directory) {
  let root = resolve(directory);
  while (!existsSync(join(root, ".code-flow/config.yml"))) {
    const parent = dirname(root);
    if (parent === root) throw new Error(`No code-flow runtime for OpenCode session at ${directory}`);
    root = parent;
  }
  return join(root, ".code-flow/scripts/cf_opencode_event.py");
}

/** Combine model-visible feedback without dropping earlier gate failures. */
export function mergePending(existing, incoming) {
  return [existing, incoming].filter(Boolean).join("\n\n");
}

function callRuntime(directory, kind, event, signal) {
  return new Promise((accept, reject) => {
    const child = execFile(process.platform === "win32" ? "py" : "python3",
      [...(process.platform === "win32" ? ["-3"] : []), runtimeScript(directory)],
      { cwd: directory, timeout: kind === "session.idle" ? IDLE_TIMEOUT : HOOK_TIMEOUT,
        maxBuffer: 1024 * 1024, signal }, (error, stdout, stderr) => {
        if (error) return reject(new Error(`code-flow native runtime: ${error.message}; ${stderr.trim()}`));
        if (stderr.trim()) console.error(stderr.trim());
        try {
          const result = JSON.parse(stdout);
          if (result.error) throw new Error(result.error);
          if (typeof result.context !== "string" || typeof result.blocked !== "boolean") {
            throw new Error("Invalid code-flow native RPC response");
          }
          accept(result);
        } catch (failure) { reject(failure); }
      });
    child.stdin.on("error", reject);
    child.stdin.end(JSON.stringify({ directory, kind, event }));
  });
}

function createState() {
  const pending = new Map();
  const jobs = new Map();
  let disposed = false;
  return {
    fault: "",
    queue(sid, text) { if (!disposed && text) pending.set(sid, mergePending(pending.get(sid), text)); },
    consume(sid) { const text = pending.get(sid); pending.delete(sid); return text; },
    async wait(sid) { await jobs.get(sid); },
    run(sid, operation) {
      const job = (jobs.get(sid) || Promise.resolve()).then(operation, operation);
      jobs.set(sid, job);
      return job.finally(() => { if (jobs.get(sid) === job) jobs.delete(sid); });
    },
    clear(sid) { pending.delete(sid); },
    dispose() { disposed = true; pending.clear(); jobs.clear(); },
  };
}

async function sessionInfo(ctx, sid) {
  if (typeof sid !== "string" || !sid) throw new Error("OpenCode native event requires sessionID");
  const info = await ctx.session.get({ sessionID: sid });
  if (typeof info?.location?.directory !== "string" || !isAbsolute(info.location.directory)) {
    throw new Error(`OpenCode session ${sid} has no absolute location.directory`);
  }
  return info;
}

async function invoke(ctx, state, kind, event, signal) {
  let result;
  try {
    const info = await sessionInfo(ctx, event.sessionID);
    result = await callRuntime(info.location.directory, kind, event, signal);
  } catch (error) {
    if (!signal.aborted) {
      const message = `code-flow OpenCode: ${error.message}`;
      // The event subscriber owns idle error feedback, including lookup errors.
      if (kind !== "session.idle") state.queue(event.sessionID, message);
      console.error(message);
    }
    throw error;
  }
  state.queue(event.sessionID, result.context);
  if (result.blocked && ["tool.before", "session.prompt"].includes(kind)) throw new Error(result.context);
}

async function registerHooks(ctx, state, signal) {
  await ctx.session.hook("prompt", event => {
    if (!event.prompt?.text?.trim()) return;
    return state.run(event.sessionID, () => invoke(ctx, state, "session.prompt", event, signal));
  });
  await ctx.session.hook("context", async event => {
    try { await state.wait(event.sessionID); } catch (error) {
      console.error(`code-flow pending event failed: ${error.message}`);
    }
    const text = mergePending(state.consume(event.sessionID), state.fault);
    state.fault = "";
    if (text) event.system.push({ type: "text", text });
  });
  await ctx.tool.hook("execute.before", event => {
    if (!["edit", "write", "patch"].includes(event.tool)) return;
    return state.run(event.sessionID, () => invoke(ctx, state, "tool.before", event, signal));
  });
  await ctx.tool.hook("execute.after", async event => {
    if (!["edit", "write", "patch"].includes(event.tool)) return;
    try {
      await state.run(event.sessionID, () => invoke(ctx, state, "tool.after", event, signal));
    } catch (error) {
      // The mutation has already happened. Preserve its result and expose the
      // runtime error through the next native context hook.
      if (!signal.aborted) console.error(`code-flow post-edit check failed: ${error.message}`);
    }
  });
}

async function observeIdle(ctx, state, event, signal) {
  const sid = event.data?.sessionID;
  if (!sid) throw new Error("OpenCode session.idle requires data.sessionID");
  const info = await sessionInfo(ctx, sid);
  if (resolve(info.location.directory) !== resolve(ctx.location.directory)) return;
  if (info.parentID) {
    const parent = await sessionInfo(ctx, info.parentID);
    if (resolve(parent.location.directory) === resolve(info.location.directory)) return;
  }
  await state.run(sid, () => invoke(ctx, state, "session.idle", { sessionID: sid }, signal));
}

async function subscribe(ctx, state, signal) {
  try {
    for await (const event of ctx.event.subscribe({ signal })) {
      try {
        if (event.type === "session.deleted") state.clear(event.data.sessionID);
        if (event.type === "session.idle") await observeIdle(ctx, state, event, signal);
      } catch (error) {
        if (signal.aborted) return;
        state.queue(event.data?.sessionID, `code-flow idle check failed: ${error.message}`);
        console.error(`code-flow idle check failed: ${error.message}`);
      }
    }
  } catch (error) {
    if (!signal.aborted) {
      state.fault = `code-flow OpenCode event subscription failed: ${error.message}`;
      console.error(state.fault);
    }
  }
}

// V2's native definition shape. No v1 server() entry or protocol adapter.
export default {
  id: "code-flow",
  async setup(ctx) {
    const state = createState();
    const controller = new AbortController();
    await registerHooks(ctx, state, controller.signal);
    void subscribe(ctx, state, controller.signal);
    return () => { controller.abort(); state.dispose(); };
  },
};
