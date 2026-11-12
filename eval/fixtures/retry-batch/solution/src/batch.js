'use strict';
const { retry } = require('./retry');

async function retryAll(operations, options) {
  const results = [], errors = [];
  for (const operation of operations) {
    try {
      results.push(await retry(operation, options));
      errors.push(undefined);
    } catch (error) {
      results.push(undefined);
      errors.push(error);
    }
  }
  return { results, errors };
}

module.exports = { retryAll };
