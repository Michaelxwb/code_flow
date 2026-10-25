"""Run published acceptance examples through the public runtime commands."""
from __future__ import annotations

import json
from pathlib import Path
import posixpath
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_EXAMPLES = (
    "src/core/code-flow/specs/shared/scenarios-template.md",
    ".code-flow/specs/shared/scenarios-template.md",
    "docs/acceptance-contract.md",
)


def _block(relative: str, language: str) -> str:
    text = (ROOT / relative).read_text(encoding="utf-8")
    match = re.search(rf"(?m)^```{language}\n([\s\S]*?)^```", text)
    assert match is not None, f"Missing {language} example in {relative}"
    return match.group(1)


def _command(*args: str) -> dict[str, object]:
    result = subprocess.run(["node", str(ROOT / "src/cli.js"), *args], cwd=ROOT,
                            text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("relative", SCENARIO_EXAMPLES)
def test_documented_scenarios_pass_the_public_quality_gate(tmp_path: Path, relative: str) -> None:
    source = tmp_path / "order.scenarios.md"
    source.write_text(_block(relative, "yaml"), encoding="utf-8")
    report = _command("scenarios", "parse", "--file", str(source), "--quality", "--json")
    assert report["quality"]["ok"], report


def test_documented_design_and_scenarios_close_the_same_ids(tmp_path: Path) -> None:
    design = tmp_path / "order.design.md"
    design.write_text(_block("docs/acceptance-contract.md", "markdown"), encoding="utf-8")
    source = tmp_path / "order.scenarios.md"
    source.write_text(_block("docs/acceptance-contract.md", "yaml"), encoding="utf-8")
    report = _command("design", "lint", "--file", str(design), "--scenarios-file", str(source), "--json")
    assert report["decision"] == "pass", report


def test_package_includes_every_linked_user_guide() -> None:
    result = subprocess.run(["npm", "pack", "--dry-run", "--ignore-scripts", "--json"], cwd=ROOT,
                            text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    packed = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    missing: set[str] = set()
    for relative in packed:
        if relative != "README.md" and not relative.startswith("docs/"):
            continue
        text = re.sub(r"```[\s\S]*?```", "", (ROOT / relative).read_text(encoding="utf-8"))
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = link.split("#", 1)[0]
            if not target or re.match(r"[a-z]+:", target):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
            if target not in packed:
                missing.add(target)
    assert not missing, f"Linked guides missing from npm package: {sorted(missing)}"
