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
    if (state === 'basic' || state === 'literal') {
      out += char;
      if (char === '\\' && state === 'basic' && text[index + 1] && text[index + 1] !== '\n') {
        out += text[++index];
      } else if (char === (state === 'basic' ? '"' : "'")) state = 'normal';
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
    if (char === '"') { out += char; state = 'basic'; continue; }
    if (char === "'") { out += char; state = 'literal'; continue; }
    out += char;
  }
  return out;
}

function quoted(text, index, quote) {
  let value = '', current = index + 1;
  while (current < text.length) {
    const char = text[current];
    if (char === quote) return { value, index: current + 1 };
    if (quote === '"' && char === '\\' && current + 1 < text.length) {
      const escape = text[current + 1];
      if (escape === 'u' && /^[0-9a-fA-F]{4}$/.test(text.slice(current + 2, current + 6))) {
        value += String.fromCodePoint(parseInt(text.slice(current + 2, current + 6), 16));
        current += 6; continue;
      }
      if (escape === 'U' && /^[0-9a-fA-F]{8}$/.test(text.slice(current + 2, current + 10))) {
        value += String.fromCodePoint(parseInt(text.slice(current + 2, current + 10), 16));
        current += 10; continue;
      }
      const map = { b: '\b', t: '\t', n: '\n', f: '\f', r: '\r', '"': '"', '\\': '\\' };
      value += Object.hasOwn(map, escape) ? map[escape] : escape;
      current += 2; continue;
    }
    value += char; current++;
  }
  return null;
}

function keyPath(text, start) {
  const parts = [];
  let index = start;
  while (index < text.length) {
    while (index < text.length && /[ \t]/.test(text[index])) index++;
    if (text[index] === '"' || text[index] === "'") {
      const parsed = quoted(text, index, text[index]);
      if (!parsed) return null;
      parts.push(parsed.value); index = parsed.index;
    } else {
      const match = /^[A-Za-z0-9_-]+/.exec(text.slice(index));
      if (!match) return null;
      parts.push(match[0]); index += match[0].length;
    }
    while (index < text.length && /[ \t]/.test(text[index])) index++;
    if (text[index] !== '.') break;
    index++;
  }
  return { parts, index };
}

function tableHeader(line) {
  const text = line.trim();
  if (!text.startsWith('[')) return null;
  const array = text.startsWith('[['), open = array ? 2 : 1;
  const close = array ? ']]' : ']';
  if (!text.endsWith(close)) return null;
  const parsed = keyPath(text, open);
  if (!parsed || parsed.index !== text.length - close.length) return null;
  return { parts: parsed.parts, array };
}

function assignmentInfo(line) {
  let quote = null, index = 0;
  for (; index < line.length; index++) {
    const char = line[index];
    if (quote) {
      if (char === '\\' && quote === '"') index++;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") { quote = char; continue; }
    if (char === '=') {
      const parsed = keyPath(line, 0);
      return parsed && parsed.index === index ? { parts: parsed.parts, index } : null;
    }
  }
  return null;
}

function samePath(left, right) {
  return left.length === right.length && left.every((part, index) => part === right[index]);
}

function inlineFeatures(text) {
  for (const line of mask(text).split('\n')) {
    const found = assignmentInfo(line);
    if (!found || !samePath(found.parts, ['features'])) continue;
    if (/^\s*\{/.test(line.slice(found.index + 1))) return true;
  }
  return false;
}

function featuresHooks(text) {
  const lines = mask(text).split('\n');
  let table = [], header = -1, end = -1, key = -1, array = false;
  for (let index = 0; index < lines.length; index++) {
    const head = tableHeader(lines[index]);
    if (head) {
      if (header >= 0) { end = index; break; }
      table = head.parts;
      if (!head.array && samePath(head.parts, ['features'])) header = index;
      if (head.array && samePath(head.parts, ['features'])) array = true;
      continue;
    }
    const found = assignmentInfo(lines[index]);
    if (!found) continue;
    if (header >= 0 && samePath(table, ['features']) && samePath(found.parts, ['hooks'])) key = index;
    else if (header < 0 && table.length === 0 && samePath(found.parts, ['features', 'hooks'])) key = index;
  }
  if (header < 0 && key < 0) return { header: -1, end: -1, key: -1, array };
  if (header >= 0 && end < 0) end = lines.length;
  return { header, end, key, array };
}

module.exports = { mask, featuresHooks, inlineFeatures };
