#!/usr/bin/env node
'use strict';
process.stdout.on('error', error => {
  if (error.code !== 'EPIPE') process.stderr.write('code-flow stdout: ' + error.message + '\n');
  process.exitCode = process.argv[2] === 'hook' ? 0 : 1;
});
require('../lib/cli').main(process.argv.slice(2)).then(code => {
  process.exitCode = code;
}).catch(error => {
  process.stderr.write('code-flow: ' + error.message + '\n');
  process.exitCode = process.argv[2] === 'hook' ? 0 : 1;
});
