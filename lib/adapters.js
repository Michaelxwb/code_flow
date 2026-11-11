'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const toml = require('./toml');
const MARKER = 'code-flow:v1';
const PLATFORMS = {
  claude: { hooks: '.claude/settings.local.json', instructions: 'CLAUDE.md', skills: '.claude/commands' },
  costrict: { hooks: '.costrict/settings.local.json', instructions: 'CLAUDE.md', skills: '.costrict/commands' },
  codex: { hooks: '.codex/hooks.json', instructions: 'AGENTS.md', skills: '.agents/skills' },
  opencode: { hooks: '.opencode/plugins/code-flow/index.js', instructions: 'AGENTS.md', skills: '.opencode/commands' }
};
function shellQuote(text) { return "'" + text.replace(/'/g, "'\\''") + "'"; }
function psQuote(text) { return "'" + text.replace(/'/g, "''") + "'"; }
function posix(node, entry, format) {
  return '# ' + MARKER + '\nif [ -x ' + shellQuote(node) + ' ] && [ -f ' + shellQuote(entry) + ' ]; then\n' +
    '  ' + shellQuote(node) + ' ' + shellQuote(entry) + ' hook prompt --format=' + format + '\n' +
    '  cf_hook_status=$?\n  if [ "$cf_hook_status" -ne 0 ]; then printf "code-flow Hook failed\\n" >&2; fi\n' +
    'else printf "code-flow global entry missing; run init again\\n" >&2; fi\nexit 0';
}
function powershell(node, entry, format) {
  return '# ' + MARKER + '\ntry { if ((Test-Path -LiteralPath ' + psQuote(node) + ') -and ' +
    '(Test-Path -LiteralPath ' + psQuote(entry) + ')) { & ' + psQuote(node) + ' ' + psQuote(entry) +
    ' hook prompt --format=' + format + ' } else { [Console]::Error.WriteLine("code-flow global entry missing") } } ' +
    'catch { [Console]::Error.WriteLine($_.Exception.Message) }; exit 0';
}
function windows(node, entry, format) {
  const quote = value => '"' + value.replace(/%/g, '%%') + '"';
  return 'rem ' + MARKER + '\r\nif not exist ' + quote(node) + ' exit /b 0\r\n' +
    'if not exist ' + quote(entry) + ' exit /b 0\r\n' + quote(node) + ' ' + quote(entry) +
    ' hook prompt --format=' + format + '\r\nexit /b 0';
}
function managed(hook) {
  if (typeof hook?.command !== 'string') return false;
  return hook.command.startsWith('# ' + MARKER + '\n') ||
    hook.command.startsWith('rem ' + MARKER + '\r\n') ||
    /(?:^|[\s/\\'"])\.code-flow[\\/]launcher[\\/]hook\.(?:sh|cmd|ps1)(?:$|[\s'"])/.test(hook.command) ||
    /\.code-flow[\\/]launcher[\\/]hook\.(?:cmd|ps1)/.test(String(hook.commandWindows || ''));
}
function owned(text) {
  if (text === null) return false;
  if (/^\/\/ code-flow:v1\r?\n/.test(text)) return true;
  if (/^---\r?\n[\s\S]*?\r?\n---\r?\n<!-- code-flow:v1 -->\r?\n/.test(text)) return true;
  if (text.trimStart().startsWith('{')) {
    try { return JSON.parse(text).managed === MARKER; } catch (error) {
      throw new f.FlowError('config_format', 'Invalid managed JSON: ' + error.message);
    }
  }
  return false;
}
function launcherCommand(platform, operatingSystem = process.platform) {
  const format = platform;
  if (operatingSystem === 'win32') {
    return {
      command: 'powershell -NoProfile -Command "if (Test-Path -LiteralPath \'.code-flow\\launcher\\hook.ps1\') ' +
        '{ & \'.code-flow\\launcher\\hook.ps1\' -Format ' + format + ' }; exit 0"',
      shell: 'powershell'
    };
  }
  return { command: "if [ -f '.code-flow/launcher/hook.sh' ]; then sh '.code-flow/launcher/hook.sh' " +
    format + '; fi; exit 0' };
}

function hook(platform, _node, _entry, operatingSystem = process.platform) {
  const result = { type: 'command', command: launcherCommand(platform, operatingSystem).command, timeout: 5 };
  if (operatingSystem === 'win32' && !result.shell) result.shell = 'powershell';
  if (platform === 'codex') result.commandWindows =
    'cmd /c if exist ".code-flow\\launcher\\hook.cmd" (call ".code-flow\\launcher\\hook.cmd" ' +
    platform + ') & exit /b 0';
  if (platform === 'claude') result.onFailure = 'continue';
  return result;
}
function mergeHooks(raw, platform, node, entry) {
  const data = raw === null ? {} : f.object(JSON.parse(raw), 'platform configuration');
  const hooks = data.hooks === undefined ? {} : f.object(data.hooks, 'hooks');
  for (const [event, groups] of Object.entries(hooks)) {
    f.demand(Array.isArray(groups), 'hooks_invalid', 'Hook groups must be arrays');
    hooks[event] = groups.map(group => {
      f.object(group, 'Hook group');
      f.demand(Array.isArray(group.hooks), 'hooks_invalid', 'group.hooks must be an array');
      return { ...group, hooks: group.hooks.filter(item => !managed(item)) };
    }).filter(group => group.hooks.length > 0);
    if (!hooks[event].length) delete hooks[event];
  }
  hooks.UserPromptSubmit = [...(hooks.UserPromptSubmit || []), { hooks: [hook(platform, node, entry)] }];
  return JSON.stringify({ ...data, hooks }, null, 2) + '\n';
}
function instructions(raw, content) {
  const start = '<!-- ' + MARKER + ' start -->', end = '<!-- ' + MARKER + ' end -->';
  const block = start + '\n' + content.trim() + '\n' + end;
  const text = raw ?? '';
  const a = text.indexOf(start), b = text.indexOf(end);
  f.demand((a < 0 && b < 0) || (a >= 0 && b > a && text.indexOf(start, a + 1) < 0 && text.indexOf(end, b + 1) < 0),
    'instructions_invalid', 'Invalid code-flow managed instruction markers');
  return a < 0 ? text.trimEnd() + (text ? '\n\n' : '') + block + '\n' :
    text.slice(0, a) + block + text.slice(b + end.length);
}
function codexConfig(raw) {
  const text = raw ?? '';
  f.demand(!toml.inlineFeatures(text),
    'config_format', 'Use a [features] table in Codex config.toml before init');
  const found = toml.featuresHooks(text);
  f.demand(!found.array, 'config_format', 'Use a [features] table, not an array table');
  const lines = text.split('\n');
  if (found.header < 0 && found.key < 0) {
    if (found.rootFeatures >= 0) {
      f.demand(!toml.valueMultiline(text, found.rootFeatures), 'config_format',
        'Multi-line features.* values are not supported before init');
      lines.splice(found.rootFeatures + 1, 0, 'features.hooks = true');
      return lines.join('\n').replace(/\n*$/, '\n');
    }
    return text.trimEnd() + (text ? '\n\n' : '') + '[features]\nhooks = true\n';
  }
  if (found.header >= 0 && found.key < 0) {
    lines.splice(found.header + 1, 0, 'hooks = true');
  } else if (found.key >= 0) {
    const line = lines[found.key];
    const clean = line.replace(/\r$/, '');
    const match = /^(\s*[^=]*=\s*)(true|false)(\s*(?:#.*)?)(\r?)$/.exec(clean);
    f.demand(match, 'config_format', 'Invalid features.hooks');
    lines[found.key] = match[1] + 'true' + match[3] + (line.endsWith('\r') ? '\r' : '');
  }
  return lines.join('\n').replace(/\n*$/, '\n');
}
function plugin(node, entry) {
  return fs.readFileSync(path.join(__dirname, '../templates/adapters/opencode.mjs'), 'utf8')
    .replace('__CODE_FLOW_NODE__', JSON.stringify(node)).replace('__CODE_FLOW_ENTRY__', JSON.stringify(entry));
}
module.exports = { PLATFORMS, MARKER, managed, owned, hook, mergeHooks, instructions, codexConfig, plugin, posix, windows, powershell };
