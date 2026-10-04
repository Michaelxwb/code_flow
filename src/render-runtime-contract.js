'use strict';

// Development generator: command examples in skills come from the runtime contract.
const fs = require('fs');
const path = require('path');
const registry = require('./core/code-flow/runtime-commands.json');
const { commands } = registry;
const start = '<!-- code-flow:runtime-commands start -->';
const end = '<!-- code-flow:runtime-commands end -->';

function markdownFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? markdownFiles(file) : file.endsWith('.md') ? [file] : [];
  });
}

function render(content) {
  const original = content.split(start)[0].trimEnd();
  const used = Object.keys(commands).filter(command => original.includes(`code-flow ${command}`));
  if (!used.length) return original + '\n';
  const examples = used.map(command => `code-flow ${command} ${commands[command].example_args}`).join('\n');
  return `${original}\n\n${start}\n\n运行时命令示例（由命令契约生成；实际参数见各命令 --help）：\n\n\`\`\`bash\n${examples}\n\`\`\`\n\n${end}\n`;
}

function generate() {
  for (const [platform, area] of [['claude', 'commands'], ['costrict', 'commands'],
    ['opencode', 'commands'], ['codex', 'skills']]) {
    const directory = path.join(__dirname, 'adapters', platform, area);
    for (const file of markdownFiles(directory)) {
      fs.writeFileSync(file, render(fs.readFileSync(file, 'utf8')));
    }
  }
}

if (require.main === module) generate();
module.exports = { render };
