'use strict';
const fs = require('node:fs');
const { object, demand, FlowError } = require('./fs');

function parse(raw) {
  const bom = raw.startsWith('\ufeff') ? '\ufeff' : '';
  const text = raw.slice(bom.length);
  const match = text.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  demand(match, 'frontmatter_missing', 'Expected JSON frontmatter');
  let meta;
  try { meta = JSON.parse(match[1]); } catch (error) {
    throw new FlowError('frontmatter_invalid', 'Invalid JSON frontmatter: ' + error.message);
  }
  object(meta, 'frontmatter');
  return { meta, body: text.slice(match[0].length), header: match[0], bom,
    eol: match[0].includes('\r\n') ? '\r\n' : '\n', raw };
}
function stringify(document, meta = document.meta, body = document.body) {
  const eol = document.eol || '\n';
  const header = document.header && JSON.stringify(meta) === JSON.stringify(document.meta)
    ? document.header : '---' + eol + JSON.stringify(meta, null, 2).replace(/\n/g, eol) + eol + '---' + eol;
  return (document.bom || '') + header + body;
}
function create(meta, body = '') {
  return stringify({ meta: {}, body, eol: '\n', bom: '' }, meta, body);
}
function readHeader(file) {
  const fd = fs.openSync(file, 'r');
  const chunks = [];
  try {
    for (let total = 0; total < 65536; total += 1024) {
      const buffer = Buffer.alloc(1024);
      const size = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (!size) break;
      chunks.push(buffer.subarray(0, size));
      const text = Buffer.concat(chunks).toString('utf8');
      if (/^\ufeff?---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/.test(text)) return parse(text).meta;
    }
    throw new FlowError('frontmatter_missing', 'Missing or oversized JSON frontmatter: ' + file);
  } finally { fs.closeSync(fd); }
}
module.exports = { parse, stringify, create, readHeader };
