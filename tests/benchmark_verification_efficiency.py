"""Reproducible isolated validator baseline for TASK-001."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.task.cf_requirement_verification import verify_layers


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _project(root: Path) -> Path:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Benchmark")
    _git(root, "config", "user.email", "benchmark@example.invalid")
    (root / ".code-flow").mkdir()
    (root / ".gitignore").write_text(".code-flow/\n*.runs\n", encoding="utf-8")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "auth.py").write_text("AUTH = 1\n", encoding="utf-8")
    (root / "notes.txt").write_text("unchanged\n", encoding="utf-8")
    (root / "check.py").write_text(
        "from pathlib import Path\np = Path('check.runs')\n"
        "p.write_text((p.read_text() if p.exists() else '') + 'x')\n", encoding="utf-8")
    (root / ".code-flow/validation.yml").write_text(
        f'validators:\n  - name: check\n    trigger: "*.py"\n'
        f'    command: "{sys.executable} check.py"\n    timeout: 30000\n', encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root / ".code-flow"


def _sample(root: Path, demand: Path, repeat: int, scenario: str) -> dict[str, object]:
    result = verify_layers(str(root), str(demand), layers="validators", profile="full")
    if result.get("decision") != "pass" or "timings" not in result:
        raise RuntimeError(f"benchmark verification failed: {result.get('reason', 'missing timings')}")
    return {"repeat": repeat, "scenario": scenario, "timings": result["timings"],
            "executed": result["executed"], "reused": result["reused"],
            "input_change_category": result["input_change_category"]}


def measure() -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for repeat in range(1, 4):
        with tempfile.TemporaryDirectory(prefix="cf-verification-baseline-") as directory:
            root = Path(directory)
            demand = _project(root)
            samples.append(_sample(root, demand, repeat, "cold"))
            samples.append(_sample(root, demand, repeat, "unchanged"))
            (root / "notes.txt").write_text("unrelated change\n", encoding="utf-8")
            samples.append(_sample(root, demand, repeat, "unrelated"))
            (root / "auth.py").write_text("AUTH = 2\n", encoding="utf-8")
            samples.append(_sample(root, demand, repeat, "shared_dependency"))
    return samples


def summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for name in ("cold", "unchanged", "unrelated", "shared_dependency"):
        rows = [row for row in samples if row["scenario"] == name]
        summary[name] = {"samples": len(rows),
                         "median_elapsed_ms": statistics.median(
                             float(row["timings"]["elapsed_ms"]) for row in rows),
                         "executed": [row["executed"] for row in rows],
                         "reused": [row["reused"] for row in rows]}
    return summary


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: benchmark_verification_efficiency.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    samples = measure()
    (output / "baseline-raw.json").write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")
    (output / "baseline-summary.json").write_text(json.dumps(summarize(samples), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
