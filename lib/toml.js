'use strict';

function mask(text) {
  let out = '', state = 'normal';
  for (let index = 0; index < text.length; index++) {
    const char = text[index], next = text.slice(index, index + 3);
    if (char === '\n') {
      out += '\n';
      if (state === 'comment' || state === 'basic' || state === 'literal') state = 'normal';
      continue;
    }
    if (state === 'comment') { out += ' '; continue; }
    if (state === 'basic') {
      if (char === '\\') { out += ' '; if (text[index + 1] && text[index + 1] !== '\n') { out += ' '; index++; } continue; }
      out += ' ';
      if (char === '"') state = 'normal';
      continue;
    }
    if (state === 'literal') {
      out += ' ';
      if (char === "'") state = 'normal';
      continue;
    }
    if (state === 'multibasic') {
      if (next === '"""') { out += '   '; index += 2; state = 'normal'; continue; }
      out += ' ';
      if (char === '\\' && text[index + 1] && text[index + 1] !== '\n') { out += ' '; index++; }
      continue;
    }
    if (state === 'multiliteral') {
      if (next === "'''") { out += '   '; index += 2; state = 'normal'; continue; }
      out += ' ';
      continue;
    }
    if (char === '#') { out += ' '; state = 'comment'; continue; }
    if (next === '"""') { out += '   '; index += 2; state = 'multibasic'; continue; }
    if (next === "'''") { out += '   '; index += 2; state = 'multiliteral'; continue; }
    if (char === '"') { out += ' '; state = 'basic'; continue; }
    if (char === "'") { out += ' '; state = 'literal'; continue; }
    out += char;
  }
  return out;
}

function featuresHooks(text) {
  const lines = mask(text).split('\n');
  let header = -1, end = -1;
  for (let index = 0; index < lines.length; index++) {
    const match = /^\s*\[([^\[\]]*)\]\s*$/.exec(lines[index]);
    if (!match) continue;
    if (header >= 0) { end = index; break; }
    if (match[1].trim() === 'features') header = index;
  }
  if (header < 0) return { header: -1, end: -1, key: -1 };
  if (end < 0) end = lines.length;
  let key = -1;
  for (let index = header + 1; index < end; index++) {
    if (/^\s*hooks\s*=/.test(lines[index])) { key = index; break; }
  }
  return { header, end, key };
}

module.exports = { mask, featuresHooks };
