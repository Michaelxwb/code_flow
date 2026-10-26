#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.hooks.cf_post_hook."""
import sys

from codeflow.hooks import cf_post_hook as _impl

if __name__ == "__main__":
    _impl.main()
    _impl.timing_log("cf_post_hook")
else:
    sys.modules[__name__] = _impl
