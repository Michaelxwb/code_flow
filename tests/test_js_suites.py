"""Run the JavaScript suites from the documented pytest entry.

`pytest -q tests` previously skipped `tests/*.js`, which let the runtime ignore
list drift for several releases. This wrapper makes every JS suite part of the
default flow. `KNOWN_FAILURES` is a ratchet: a listed suite must still fail, so
the entry has to be deleted as soon as its fix lands.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_SUITES = sorted((ROOT / "tests").glob("test_*.js"))

KNOWN_FAILURES: dict[str, str] = {}


def _run_suite(node: str, suite: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [node, str(suite)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_javascript_suites() -> None:
    assert JS_SUITES, "no tests/test_*.js suites found"
    node = shutil.which("node")
    assert node is not None, "node is required (package.json engines >=18)"
    failures: list[str] = []
    unexpected_passes: list[str] = []
    for suite in JS_SUITES:
        result = _run_suite(node, suite)
        output = (result.stdout + result.stderr).strip()[-2000:]
        reason = KNOWN_FAILURES.get(suite.name)
        if reason is None:
            if result.returncode != 0:
                failures.append(f"{suite.name} (exit {result.returncode})\n{output}")
            continue
        if result.returncode == 0:
            unexpected_passes.append(suite.name)
    assert not failures, "JavaScript suites failed:\n\n" + "\n\n".join(failures)
    assert not unexpected_passes, (
        "known failures now pass; remove them from KNOWN_FAILURES: "
        + ", ".join(unexpected_passes)
    )
