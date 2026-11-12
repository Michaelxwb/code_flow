'use strict';
const { retry } = require('./retry');

async function retryAll(operations, options) {
  const results = [], ledger = [];
  for (let index = 0; index < operations.length; index++) {
    const operation = operations[index];
    try {
      results.push(await retry(operation, options));
      ledger.push({ seq: index + 1, ref: operation.id ?? null, outcome: 'PASS' });
    } catch (error) {
      results.push(undefined);
      ledger.push({ seq: index + 1, ref: operation.id ?? null, outcome: 'FAIL_RETRY_EXHAUSTED' });
    }
  }
  return { results, ledger };
}

module.exports = { retryAll };
