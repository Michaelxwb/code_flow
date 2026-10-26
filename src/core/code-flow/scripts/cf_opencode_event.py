#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.hooks.cf_opencode_event."""
import sys

from codeflow.hooks import cf_opencode_event as _impl

if __name__ == "__main__":
    _impl.main()
else:
    sys.modules[__name__] = _impl
