'use strict';

function fenceMarker(line, current) {
  const match = /^\s*(`{3,}|~{3,})/.exec(line);
  if (!match) return null;
  const token = match[1];
  if (!current) return { next: token };
  const closes = token[0] === current[0] && token.length >= current.length &&
    line.slice(match[0].length).trim() === '';
  return { next: closes ? null : current };
}

module.exports = { fenceMarker };
