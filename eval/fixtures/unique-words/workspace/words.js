'use strict';

function words(text) {
  const value = String(text ?? '').trim();
  return value ? value.split(/\s+/) : [];
}

module.exports = { words };
