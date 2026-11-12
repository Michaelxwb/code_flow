'use strict';

function parseLine(line) {
  return String(line ?? '').split(',');
}

module.exports = { parseLine };
