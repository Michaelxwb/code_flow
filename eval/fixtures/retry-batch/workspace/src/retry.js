'use strict';

async function retry(operation, { attempts = 3, baseDelayMs = 10 } = {}) {
  let last;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await operation(attempt);
    } catch (error) {
      last = error;
      if (attempt === attempts) break;
      await new Promise(resolve => setTimeout(resolve, baseDelayMs * attempt));
    }
  }
  throw last;
}

module.exports = { retry };
