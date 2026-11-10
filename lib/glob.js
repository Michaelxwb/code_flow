'use strict';
const { demand, string } = require('./fs');

function compile(pattern) {
  string(pattern, 'glob');
  demand(!/[\\{}[\]()!]/.test(pattern) && !pattern.startsWith('/') &&
    !pattern.split('/').includes('..'), 'invalid_glob', 'Unsupported glob: ' + pattern);
  let result = '^';
  for (let i = 0; i < pattern.length; i++) {
    const char = pattern[i];
    if (char === '*' && pattern[i + 1] === '*') {
      demand((i === 0 || pattern[i - 1] === '/') &&
        (i + 2 === pattern.length || pattern[i + 2] === '/'), 'invalid_glob', 'Invalid ** glob: ' + pattern);
      if (pattern[i + 2] === '/') { result += '(?:[^/]+/)*'; i += 2; }
      else { result += '.*'; i++; }
    } else if (char === '*') result += '[^/]*';
    else if (char === '?') result += '[^/]';
    else result += char.replace(/[.+^$|]/g, '\\$&');
  }
  return new RegExp(result + '$');
}
function matches(pattern, file) { return compile(pattern).test(file.replace(/\\/g, '/')); }
module.exports = { compile, matches };
