'use strict';

function words(text) {
  const value = String(text ?? '').trim();
  return value ? value.split(/\s+/) : [];
}

function uniqueWords(text) {
  const seen = new Set(), result = [];
  for (const word of words(text)) {
    const key = word.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(word);
  }
  return result;
}

module.exports = { words, uniqueWords };
