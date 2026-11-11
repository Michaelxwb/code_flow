// code-flow:v1
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
const NODE = "/Users/jahan/.nvm/versions/node/v24.17.0/bin/node";
const ENTRY = "/Users/jahan/workspace/code_flow/bin/code-flow.js";
function invoke(directory, event, signal) {
  return new Promise((resolve, reject) => {
    const bridge = join(directory, ".code-flow/launcher/bridge.cjs");
    const useBridge = existsSync(bridge);
    const command = existsSync(NODE) ? NODE : process.execPath;
    const args = useBridge
      ? [bridge, "--format", "opencode", "--node", NODE, "--entry", ENTRY]
      : [ENTRY, "hook", "prompt", "--format=opencode"];
    const child = execFile(command, args,
      { cwd: directory, timeout: 3000, maxBuffer: 131072, windowsHide: true, signal },
      (error, stdout, stderr) => {
        if (stderr.trim()) console.error(stderr.trim());
        if (error) return reject(error);
        try {
          const result = stdout.trim() ? JSON.parse(stdout) : { context: "" };
          if (typeof result.context !== "string") throw new Error("Invalid code-flow context");
          resolve(result.context);
        } catch (failure) { reject(failure); }
      });
    child.stdin.on("error", reject);
    child.stdin.end(JSON.stringify({ directory, event }));
  });
}
export default {
  id: "code-flow",
  async setup(ctx) {
    const pending = new Map(), jobs = new Map(), controller = new AbortController();
    const diagnose = error => { if (!controller.signal.aborted) console.error("code-flow: " + error.message); };
    try {
      await ctx.session.hook("prompt", event => {
        if (controller.signal.aborted) return;
        if (typeof event?.prompt?.text !== "string" || !event.prompt.text.trim()) return;
        const sid = event.sessionID;
        const previous = jobs.get(sid) || Promise.resolve();
        const job = previous.then(async () => {
          if (typeof sid !== "string" || !sid) throw new Error("Missing native sessionID");
          const info = await ctx.session.get({ sessionID: sid });
          if (!isAbsolute(info?.location?.directory || "")) throw new Error("Missing session directory");
          const text = await invoke(info.location.directory, event, controller.signal);
          if (!controller.signal.aborted) pending.set(sid, text);
        }).catch(error => {
          pending.delete(sid);
          diagnose(error);
        });
        jobs.set(sid, job);
        void job.finally(() => { if (jobs.get(sid) === job) jobs.delete(sid); });
        return job;
      });
      await ctx.session.hook("context", async event => {
        try {
          await jobs.get(event.sessionID);
          const text = pending.get(event.sessionID);
          if (text && !controller.signal.aborted) event.system.push({ type: "text", text });
        } catch (error) { diagnose(error); }
      });
    } catch (error) { diagnose(error); }
    return () => { controller.abort(); pending.clear(); jobs.clear(); };
  }
};
