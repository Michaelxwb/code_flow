"""Shared lifecycle predicate without loading the workflow runtime.

0.8 adds an explicit provisional state: a TASK whose required code checks were
not actually executed must never look finished. Keep the finished set narrow so
dependency resolution, parallel collect and archive cannot treat provisional
work as complete.
"""

FINISHED_STATUSES = ("done", "verified")
