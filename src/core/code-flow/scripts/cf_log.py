#!/usr/bin/env python3
# coding: utf-8
import atexit
import datetime
import os
import random
import sys

LOG_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../logs")
)

# fix#2: module-level save of original stdout, enables restore_stdout() rollback
_original_stdout = sys.stdout


class StdoutLogTee:
    def __init__(self, prefix: str | None = None) -> None:
        self._file_path = self._init_log_path(prefix)  # fix#5: private method
        # fix#2: bind to real stdout, prevent chain tee on repeated calls
        self._stream = _original_stdout
        # fix#3: track actual bytes, replace bool _has_content
        self._bytes_written = 0
        self._closed = False
        self._file = open(self._file_path, "a", encoding="utf-8")
        atexit.register(self.close)

    def write(self, data: str) -> int:
        # fix#1: stdout write first; file write failure degrades to stderr warning, does not block main flow
        n = self._stream.write(data)
        self._bytes_written += len(data)  # fix#3
        try:
            self._file.write(data)
        except OSError as err:
            self._err_log(f"log write error: {err}")
        return n

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def _err_log(self, err_msg: str) -> None:
        # fix#5: private method
        print(err_msg, file=sys.stderr)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # fix#4: unregister on manual close, prevent handler accumulation
        atexit.unregister(self.close)
        try:
            self._file.close()
        except OSError as err:
            self._err_log(f"close error: {err}")
        finally:
            # fix#4: inside finally, empty-file cleanup runs even if file.close() raises
            # fix#3: use _bytes_written, avoid false positive from write("")
            if not self._bytes_written and os.path.isfile(self._file_path):
                try:
                    os.remove(self._file_path)
                except OSError as err:
                    self._err_log(f"remove empty logfile error: {err}")

    def _init_log_path(self, prefix: str | None) -> str:
        if not prefix:
            prefix = "default"
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S") + f"{now.microsecond // 1000:03d}"
        rand_suffix = f"{random.randint(0, 999):03d}"
        log_file_name = f"{timestamp}_{rand_suffix}.log"

        log_path = os.path.join(LOG_ROOT, prefix, log_file_name)
        log_dir = os.path.join(LOG_ROOT, prefix)

        # makr sure log_dir
        os.makedirs(log_dir, exist_ok=True)
        return log_path


def reset_stdout(prefix: str | None = None) -> "StdoutLogTee":
    tee = StdoutLogTee(prefix)
    sys.stdout = tee
    return tee


def restore_stdout() -> None:
    # fix#2: new, roll back to original stdout
    sys.stdout = _original_stdout
