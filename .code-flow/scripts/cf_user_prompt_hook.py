#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.hooks.cf_user_prompt_hook."""
import sys

from codeflow.hooks import cf_user_prompt_hook as _impl

if __name__ == "__main__":
    _impl.main()
    _impl.timing_log("cf_user_prompt_hook")
else:
    sys.modules[__name__] = _impl
