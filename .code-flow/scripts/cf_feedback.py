#!/usr/bin/env python3
"""Path-frozen entry shim: implementation lives in codeflow.cli.cf_feedback."""
import sys

from codeflow.cli import cf_feedback as _impl

if __name__ == "__main__":
    sys.exit(_impl.main(sys.argv[1:]))
else:
    sys.modules[__name__] = _impl
