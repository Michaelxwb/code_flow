// Keep the CommonJS suite entry; the ESM test uses top-level await for native
// callbacks and child processes, which keep Node alive until checks complete.
import("./test_opencode_native.mjs").catch(error => {
  console.error(error);
  process.exitCode = 1;
});
