"""User-confirmed risk acceptance, scoped to the owning TASK and scenarios."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Mapping, Optional

from cf_acceptance_schema import scenario_check_ids

AGENT_IDENTITIES = frozenset(("agent", "assistant", "claude", "claude code", "codex",
                            "opencode", "costrict", "ai", "bot"))


def risk_scenario_ids(data: Mapping[str, object], check_id: str, owner: str) -> list[str]:
    """Resolve the locked plan's ownership; never accept a free-form owner."""
    rows = data.get("scenarios", [])
    if not isinstance(rows, list) or re.fullmatch(r"TASK-\d+", owner) is None:
        return []
    return sorted(str(row["id"]) for row in rows if isinstance(row, Mapping)
                  and row.get("owner") == owner and row.get("id")
                  and check_id in scenario_check_ids(row))


def _matches_scenario(risk: Mapping[str, object], check: Mapping[str, object],
                      scenario: Mapping[str, object]) -> bool:
    if risk.get("owner") != scenario.get("owner"):
        return False
    if check.get("id") not in scenario_check_ids(scenario):
        return False
    ids = risk.get("scenario_ids")
    scenario_id = scenario.get("scenario_ref") or scenario.get("id")
    # Legacy records remain valid only for scenarios owned by the recorded TASK.
    return ids is None or (isinstance(ids, list) and scenario_id in ids)


def accepted_risk(check: Optional[Mapping[str, object]],
                  scenario: Optional[Mapping[str, object]] = None) -> Optional[dict[str, object]]:
    if not isinstance(check, Mapping) or not isinstance(check.get("accepted_risk"), Mapping):
        return None
    risk = check["accepted_risk"]
    fields = ("owner", "reason", "confirmed_by", "confirmed_at", "source", "expires_at")
    if any(not isinstance(risk.get(key), str) or not str(risk[key]).strip() for key in fields):
        return None
    if re.fullmatch(r"TASK-\d+", str(risk["owner"])) is None:
        return None
    if str(risk["confirmed_by"]).strip().lower().split(":", 1)[0] in AGENT_IDENTITIES:
        return None
    expires = str(risk["expires_at"]).strip()
    try:
        deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires):
        deadline = deadline.replace(hour=23, minute=59, second=59, microsecond=999999)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= datetime.now(timezone.utc):
        return None
    if scenario is not None and not _matches_scenario(risk, check, scenario):
        return None
    return dict(risk)


def risk_counts(data: Mapping[str, object]) -> dict[str, int]:
    checks, rows = data.get("checks", []), data.get("scenarios", [])
    checks = checks if isinstance(checks, list) else []
    rows = rows if isinstance(rows, list) else []
    recorded = [check for check in checks if isinstance(check, Mapping)
                and isinstance(check.get("accepted_risk"), Mapping)]
    active = sum(any(accepted_risk(check, row) is not None for row in rows
                     if isinstance(row, Mapping)) for check in recorded)
    return {"accepted_risks": active, "recorded_risks": len(recorded),
            "inactive_risks": len(recorded) - active}
