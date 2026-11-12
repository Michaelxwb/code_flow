'use strict';
const { retry } = require('./retry');

async function retryAll(operations, options) {
  const results = [];
  for (const operation of operations) results.push(await retry(operation, options));
  return results;
}

module.exports = { retryAll };
