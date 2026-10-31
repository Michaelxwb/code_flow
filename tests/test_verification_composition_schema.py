"""Contract checks for explicit expected-to-check composition."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"))
from codeflow.acceptance.cf_scenario_source import ScenarioError, parse_scenarios
from codeflow.acceptance.cf_acceptance_schema import validate_checks


def scenario_source(mapping):
    row = {"id": "S-01", "expected": ["first", "second"],
           "checks": ["contract", "integration"], "expected_checks": mapping}
    return parse_scenarios("example.scenarios.md", text=yaml.safe_dump({"scenarios": [row]}))


def test_explicit_mapping_is_preserved_and_complete():
    mapping = [{"expected": 1, "checks": ["contract"]},
               {"expected": 2, "checks": ["integration"]}]
    assert scenario_source(mapping)["scenarios"][0]["expected_checks"] == mapping


@pytest.mark.parametrize("mapping", [
    [{"expected": 1, "checks": ["contract"]}],
    [{"expected": 1, "checks": ["unknown"]}, {"expected": 2, "checks": ["integration"]}],
    [{"expected": True, "checks": ["contract"]}, {"expected": 2, "checks": ["integration"]}],
])
def test_invalid_composition_is_rejected(mapping):
    with pytest.raises(ScenarioError):
        scenario_source(mapping)


def test_check_level_is_validated():
    check = {"id": "one", "command": ["true"], "level": "invalid"}
    with pytest.raises(ValueError, match="level"):
        validate_checks([check])
