'use strict';
const path = require('node:path');
const f = require('./fs');
const config = require('./config');
const session = require('./session');
const task = require('./task');
const render = require('./render');
function cleanPrompt(text) {
  let fence = null;
  return text.replace(/<(task-notification|output-file)\b[^>]*>[\s\S]*?(?:<\/\1>|$)/gi, '')
    .split('\n').filter(line => {
      const marker = line.match(/^\s*(`{3,}|~{3,})/);
      if (marker) {
        if (!fence) fence = marker[1];
        else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
        return false;
      }
      return !fence && !/^\s*>/.test(line);
    }).join('\n').replace(/\b[a-z]+:\/\/[^\s<>]+/gi, '');
}
function paths(prompt, root) {
  const text = prompt.replace(/^task:[^\n]*$/gm, '');
  const found = [];
  const pattern = /(?:@)?(?:"([^"\r\n]+)"|'([^'\r\n]+)'|`([^`\r\n]+)`|([A-Za-z0-9_.@/\\:-]+))/g;
  for (const match of text.matchAll(pattern)) {
    const value = (match[1] || match[2] || match[3] || match[4]).replace(/^@/, '').replace(/[.,;:]+$/, '');
    if (!/[\\/]/.test(value) && !/\.[A-Za-z][A-Za-z0-9]{0,9}$/.test(value)) continue;
    try { found.push(...render.normalizePaths(root, [value])); } catch (error) {
      if (error.code !== 'invalid_path') throw error;
    }
  }
  return [...new Set(found)];
}
function nativeEvent(data, format) {
  f.object(data, 'Hook input');
  if (format === 'opencode') {
    f.object(data.event, 'OpenCode event');
    return { cwd: data.directory, sessionId: data.event.sessionID, prompt: data.event.prompt?.text };
  }
  f.demand(['claude', 'codex', 'costrict'].includes(format), 'hook_format', 'Unknown Hook format');
  return { cwd: data.cwd, sessionId: data.session_id, prompt: data.prompt };
}
function parseTaskRef(value) {
  const match = /^(.+\.md)#(TASK-\d+)$/.exec(String(value).trim());
  f.demand(match, 'task_reference', 'Use task: <task-document>.md#TASK-NNN');
  return { taskFile: match[1], taskId: match[2] };
}

function choose(root, prompt, token, diagnostics) {
  const explicit = [...prompt.matchAll(/^task:[ \t]*(.+?)[ \t]*$/gm)].map(match => match[1]);
  if (explicit.length) {
    if (explicit.length !== 1) diagnostics.push({ code: 'task_ambiguous', message: 'Use exactly one task: <task-document>.md#TASK-NNN' });
    else {
      try {
        const ref = parseTaskRef(explicit[0]);
        const selected = task.loadTask(root, ref.taskFile, ref.taskId);
        return { taskFile: selected.relative, taskId: selected.id };
      } catch (error) { diagnostics.push({ code: error.code, message: error.message }); }
    }
    return null;
  }
  if (!token) return null;
  try {
    const binding = session.read(root, token);
    if (!binding) return null;
    const selected = task.loadTask(root, binding.task_file, binding.task_id);
    f.demand(selected.status === 'in-progress', 'binding_stale', 'Bound Task is no longer in-progress');
    return { taskFile: selected.relative, taskId: selected.id };
  } catch (error) { diagnostics.push({ code: error.code || 'binding_invalid', message: error.message }); return null; }
}
function payload(format, text) {
  return format === 'opencode' ? { context: text } :
    { hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: text } };
}
function build(data, format) {
  const diagnostics = [];
  try {
    const event = nativeEvent(data, format);
    f.demand(typeof event.prompt === 'string', 'hook_prompt', 'prompt must be a string');
    if (!event.prompt.trim()) return { payload: null, diagnostics };
    f.string(event.cwd, 'Hook cwd');
    f.demand(path.isAbsolute(event.cwd), 'hook_cwd', 'Hook cwd must be absolute');
    const root = config.findRoot(event.cwd, false);
    if (!root || !event.prompt.trim()) return { payload: null, diagnostics };
    config.load(root);
    const prompt = cleanPrompt(event.prompt);
    const token = typeof event.sessionId === 'string' && event.sessionId ?
      session.token(root, format, event.sessionId) : null;
    if (!token) diagnostics.push({ code: 'session_missing', message: 'No session ID; explicit paths remain available' });
    const selected = choose(root, prompt, token, diagnostics);
    const result = render.inject(root, { taskFile: selected?.taskFile, taskId: selected?.taskId,
      paths: paths(prompt, root), session: token });
    return { ...result, payload: payload(format, result.text), diagnostics: [...diagnostics, ...result.diagnostics] };
  } catch (error) {
    diagnostics.push({ code: error.code || 'hook_error', message: error.message });
    return { payload: payload(format, ''), diagnostics };
  }
}
module.exports = { build, payload, paths, cleanPrompt, choose, parseTaskRef, nativeEvent };
