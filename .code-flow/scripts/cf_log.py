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


class StdoutLogTee:
    def __init__(self, prefix: str | None = None) -> None:
        self._file_path = self.init_log_path(prefix)
        self._stream = sys.stdout
        self._has_content = False
        self._closed = False
        self._file = open(self._file_path, "a", encoding="utf-8")
        atexit.register(self.close)

    def write(self, data: str) -> int:
        self._has_content = True
        written = self._file.write(data)
        self._stream.write(data)
        return written

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def err_log(self, err_msg: str) -> None:
        print(err_msg, file=sys.stderr)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file.close()
        except Exception as err:
            self.err_log(f"close error: {err}")
        if not self._has_content and os.path.isfile(self._file_path):
            try:
                os.remove(self._file_path)
            except Exception as err:
                self.err_log(f"remove empty logfile error: {err}")

    def init_log_path(self, prefix: str | None) -> str:
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S") + f"{now.microsecond // 1000:03d}"
        rand_suffix = f"{random.randint(0, 999):03d}"
        log_file_name = f"{timestamp}_{rand_suffix}.log"

        if not prefix:
            log_path = os.path.join(LOG_ROOT, log_file_name)
        else:
            log_path = os.path.join(LOG_ROOT, prefix, log_file_name)

        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        return log_path


def reset_stdout(prefix: str | None = None) -> "StdoutLogTee":
    tee = StdoutLogTee(prefix)
    sys.stdout = tee
    return tee
