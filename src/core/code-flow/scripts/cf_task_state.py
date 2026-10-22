"""Shared lifecycle predicates without loading the workflow runtime.

0.8 adds an explicit provisional state: a TASK whose required code checks were
not actually executed must never look finished. Keep the finished set narrow so
dependency resolution, parallel collect and archive cannot treat provisional
work as complete.
"""

TASK_STATUSES = ("draft", "in-progress", "provisional", "done", "verified", "blocked")
FINISHED_STATUSES = ("done", "verified")
OPEN_STATUSES = ("draft", "in-progress", "provisional", "blocked")
FINISHED_OR_PROVISIONAL = ("provisional", "done", "verified")

# Scenario/check states are intentionally separate from TASK statuses. A check
# can be executed and failing while the TASK is still in-progress; only the
# runner may promote a check to verified.
SCENARIO_STATUSES = (
    "aspirational",
    "designed",
    "executed_pass",
    "verified",
    "executed_fail",
    "env_blocked",
    "accepted_risk",
    "deferred",
)
CHECK_STATUSES = (
    "designed",
    "executed_pass",
    "verified",
    "executed_fail",
    "env_blocked",
    "accepted_risk",
    "deferred",
)


def is_finished(status: str) -> bool:
    """Only done/verified satisfy dependency and archive gates."""
    return status in FINISHED_STATUSES


def is_open(status: str) -> bool:
    return status in OPEN_STATUSES


def is_provisional(status: str) -> bool:
    return status == "provisional"
