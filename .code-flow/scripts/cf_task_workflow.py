#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.cli.cf_task_workflow."""
import sys

from codeflow.cli import cf_task_workflow as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
else:
    sys.modules[__name__] = _impl
