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

function bracketDelta(line) {
  let depth = 0, quote = null;
  for (let index = 0; index < line.length; index++) {
    const char = line[index];
    if (quote) {
      if (char === '\\' && quote === '"') index++;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") { quote = char; continue; }
    if (char === '[') depth++;
    else if (char === ']') depth--;
  }
  return depth;
}

function tableHeader(line) {
  const text = line.trim();
  if (!text.startsWith('[') || !text.endsWith(']')) return null;
  const array = text.startsWith('[[') && text.endsWith(']]');
  const inner = text.slice(array ? 2 : 1, array ? -2 : -1).trim();
  if (inner === 'features') return { kind: array ? 'array' : 'features', array };
  if (/^["']/.test(inner) && (/features/i.test(inner) || /\\u/i.test(inner))) {
    return { kind: 'unsupported', array, reason: 'quoted table' };
  }
  if (/^features\./.test(inner) || /\.features\./.test(inner)) {
    return { kind: 'unsupported', array, reason: 'nested features table' };
  }
  return { kind: 'other', array };
}

function assignment(line) {
  const text = line.trim();
  if (!text || text.startsWith('[')) return null;
  if (/^["'].*=/.test(text)) return { quoted: true, text };
  const match = /^([A-Za-z0-9_.-]+)\s*=\s*(.*)$/.exec(text);
  return match ? { key: match[1], value: match[2].trim() } : null;
}

function multiline(value, line, rawLine) {
  return bracketDelta(line) !== 0 || /"""|'''/.test(rawLine.split('#')[0]);
}

function featuresHooks(text) {
  const rawLines = text.split('\n'), lines = mask(text).split('\n');
  let table = null, depth = 0, header = -1, end = -1, key = -1, value = null, array = false, rootFeatures = -1, unsupported = null;
  const fail = reason => { if (!unsupported) unsupported = reason; };
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (depth === 0) {
      const head = tableHeader(line);
      if (head) {
        if (header >= 0 && end < 0) end = index;
        if (head.kind === 'features') {
          if (header >= 0) fail('duplicate features table');
          header = index; table = 'features';
        } else if (head.kind === 'array') {
          if (header >= 0) fail('duplicate features table');
          array = true; header = index; table = 'features'; fail('array table');
        } else if (head.kind === 'unsupported') {
          fail(head.reason); table = 'other';
        } else {
          table = 'other';
        }
        depth = Math.max(0, depth + bracketDelta(line));
        continue;
      }
      const item = assignment(line);
      if (item && item.quoted) {
        if (table === 'features' || /features|hooks/i.test(item.text) || /\\u/i.test(item.text)) {
          fail('quoted key');
        }
      } else if (item && table === 'features') {
        if (item.key === 'hooks') {
          if (multiline(item.value, line, rawLines[index])) fail('Multi-line features value');
          else if (item.value === 'true' || item.value === 'false') { key = index; value = item.value; }
          else fail('features.hooks value');
        } else if (item.key.startsWith('features.')) {
          fail('dotted key inside features');
        }
      } else if (item && table === null) {
        if (item.key === 'features.hooks') {
          if (multiline(item.value, line, rawLines[index])) fail('Multi-line features value');
          else if (item.value === 'true' || item.value === 'false') { key = index; value = item.value; }
          else fail('features.hooks value');
        } else if (item.key === 'features') {
          fail('inline features value');
        } else if (item.key.startsWith('features.')) {
          rootFeatures = index;
          if (multiline(item.value, line, rawLines[index])) fail('Multi-line features value');
        }
      }
    }
    depth = Math.max(0, depth + bracketDelta(line));
  }
  if (header >= 0 && end < 0) end = lines.length;
  return { header, end, key, value, array, rootFeatures, unsupported };
}

module.exports = { featuresHooks };
