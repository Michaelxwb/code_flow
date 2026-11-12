'use strict';

function sleepDefault(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function retry(operation, { attempts = 3, baseDelayMs = 10, sleep = sleepDefault } = {}) {
  let last;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await operation(attempt);
    } catch (error) {
      if (error?.retryable !== true) throw error;
      last = error;
      if (attempt === attempts) break;
      const exponential = baseDelayMs * 2 ** (attempt - 1);
      const jitter = 0.5 + (attempt % 3) * 0.25;
      await sleep(Math.round(Math.min(1000, exponential * jitter)));
    }
  }
  throw last;
}

module.exports = { retry };
