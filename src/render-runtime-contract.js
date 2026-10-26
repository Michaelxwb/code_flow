'use strict';

// Development generator: runtime command examples and platform command bodies.
// Claude is the canonical content source; Costrict, OpenCode and Codex bodies are
// derived from it using the token bindings declared in src/adapters/platform-bindings.json.
const fs = require('fs');
const path = require('path');
const registry = require('./core/code-flow/runtime-commands.json');
const { commands } = registry;
const start = '<!-- code-flow:runtime-commands start -->';
const end = '<!-- code-flow:runtime-commands end -->';
const DEFAULT_ROOT = path.resolve(__dirname, '..');

function renderWith(commandRegistry, content) {
  const original = content.split(start)[0].trimEnd();
  const used = Object.keys(commandRegistry).filter(command => original.includes(`code-flow ${command}`));
  if (!used.length) return original + '\n';
  const examples = used.map(command => `code-flow ${command} ${commandRegistry[command].example_args}`).join('\n');
  return `${original}\n\n${start}\n\n运行时命令示例（由命令契约生成；实际参数见各命令 --help）：\n\n\`\`\`bash\n${examples}\n\`\`\`\n\n${end}\n`;
}

function render(content) {
  return renderWith(commands, content);
}

function replaceAll(content, pairs) {
  return pairs.reduce((text, [from, to]) => text.split(from).join(to), content);
}

function stripFrontmatter(content) {
  if (!content.startsWith('---\n')) return content;
  const close = content.indexOf('\n---\n', 4);
  return close === -1 ? content : content.slice(close + 5);
}

function replaceSection(content, heading, replacement) {
  const offset = content.indexOf(heading);
  if (offset === -1) throw new Error(`Missing section heading: ${heading}`);
  const next = content.slice(offset + heading.length).match(/\n#{2,3} /);
  const endOffset = next ? offset + heading.length + next.index + 1 : content.length;
  return content.slice(0, offset) + replacement + content.slice(endOffset);
}

function applySection(content, section) {
  return section ? replaceSection(content, section.heading, section.replacement) : content;
}

function applyBlankAfterTitle(content, count) {
  if (!count) return content;
  const match = content.match(/^# [^\n]*\n\n/);
  return match ? content.replace(match[0], match[0] + '\n'.repeat(count)) : content;
}

function adaptPlatform(platform, platformBinding, commandId, canonical) {
  if (platform === 'costrict') return replaceAll(canonical, platformBinding.replacements);

  const binding = platformBinding.commands[commandId];
  if (!binding) throw new Error(`Missing ${platform} binding for ${commandId}`);
  if (platform === 'opencode') {
    let body = applySection(canonical, binding.sectionReplacement);
    body = replaceAll(body, platformBinding.replacements);
    body = applyBlankAfterTitle(body, binding.blankAfterTitle);
    if (binding.description) {
      const frontmatter = `---\ndescription: ${binding.description}\n---\n${'\n'.repeat(binding.afterFrontmatterBlankLines)}`;
      return frontmatter + body;
    }
    return body;
  }

  let body = stripFrontmatter(canonical).replace(/^\n+/, '');
  body = applySection(body, binding.sectionReplacement);
  if (binding.dropTitle) {
    if (!body.startsWith('# ')) throw new Error(`${commandId}: expected a title line to drop`);
    body = body.slice(body.indexOf('\n') + 1).replace(/^\n+/, '');
  }
  for (const fragment of binding.dropText || []) {
    if (!body.includes(fragment)) throw new Error(`${commandId}: dropText not found: ${fragment.slice(0, 40)}`);
    body = body.replace(fragment, '');
  }
  body = applyBlankAfterTitle(body, binding.blankAfterTitle);
  if (binding.appendix) body += binding.appendix;
  body = replaceAll(body, platformBinding.replacements);
  for (const [from, to] of binding.restore || []) {
    if (!body.includes(from)) throw new Error(`${commandId}: restore target not found: ${from}`);
    body = body.split(from).join(to);
  }
  return `---\nname: ${commandId}\ndescription: ${binding.description}\n---\n\n${body}`;
}

function loadBindings(root) {
  return JSON.parse(fs.readFileSync(path.join(root, 'src/adapters/platform-bindings.json'), 'utf8'));
}

function loadCatalog(root) {
  return JSON.parse(fs.readFileSync(path.join(root, 'src/adapters/commands.json'), 'utf8'));
}

function commandPath(root, platform, area, command) {
  return platform === 'codex'
    ? path.join(root, 'src/adapters/codex/skills', command.id, 'SKILL.md')
    : path.join(root, 'src/adapters', platform, area, command.file);
}

function buildOutputs(root = DEFAULT_ROOT) {
  const bindings = loadBindings(root);
  const catalog = loadCatalog(root);
  const commandRegistry = require(path.join(root, 'src/core/code-flow/runtime-commands.json')).commands;
  const outputs = [];
  for (const command of catalog.commands) {
    const canonicalPath = commandPath(root, 'claude', 'commands', command);
    const canonical = renderWith(commandRegistry, fs.readFileSync(canonicalPath, 'utf8'));
    outputs.push({ path: canonicalPath, content: canonical });
    for (const [platform, platformBinding] of Object.entries(bindings.platforms)) {
      outputs.push({
        path: commandPath(root, platform, platformBinding.area, command),
        content: adaptPlatform(platform, platformBinding, command.id, canonical),
      });
    }
  }
  return outputs;
}

function check(root = DEFAULT_ROOT) {
  const drifted = buildOutputs(root).filter(output =>
    !fs.existsSync(output.path) || fs.readFileSync(output.path, 'utf8') !== output.content);
  for (const output of drifted) console.log(`drift: ${path.relative(root, output.path)}`);
  return drifted.length === 0;
}

function generate(root = DEFAULT_ROOT) {
  for (const output of buildOutputs(root)) fs.writeFileSync(output.path, output.content);
}

function main(argv) {
  const checkMode = argv.includes('--check');
  const rootIndex = argv.indexOf('--root');
  const root = rootIndex === -1 ? DEFAULT_ROOT : path.resolve(argv[rootIndex + 1]);
  if (checkMode) return check(root) ? 0 : 1;
  generate(root);
  return 0;
}

if (require.main === module) {
  const code = main(process.argv.slice(2));
  if (code !== 0) process.exit(code);
}
module.exports = { render, renderWith, buildOutputs, check, generate, main };
