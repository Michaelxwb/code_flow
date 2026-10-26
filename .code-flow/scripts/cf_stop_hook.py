#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.hooks.cf_stop_hook."""
import sys

from codeflow.hooks import cf_stop_hook as _impl

if __name__ == "__main__":
    _impl.main()
    _impl.timing_log("cf_stop_hook")
else:
    sys.modules[__name__] = _impl
