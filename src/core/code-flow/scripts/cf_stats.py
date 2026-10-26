#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.cli.cf_stats."""
import sys

from codeflow.cli import cf_stats as _impl

if __name__ == "__main__":
    _impl.main()
else:
    sys.modules[__name__] = _impl
