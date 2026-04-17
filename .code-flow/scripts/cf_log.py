#!/usr/bin/env python3
# coding: utf-8
import atexit
import datetime
import os
import random
import sys

LOG_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "../logs"))


def get_log_path(prefix: str | None) -> str:
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


class StdoutLogTee:
    def __init__(self, prefix: str = None) -> None:
        self._file_path = get_log_path(prefix)
        self._stream = sys.stdout
        self._content = ""
        self._file = open(self._file_path, "a", encoding="utf-8")
        # 注册退出时自动清理空日志文件
        atexit.register(self.close)

    def write(self, data: str) -> int:
        self._stream.write(data)
        self._content += data
        return self._file.write(data)

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def err_log(self, err_msg):
        print(err_msg, file=sys.stderr)

    def close(self):
        try:
            self._file.close()
            if not self._content.strip():
                os.remove(self._file_path)
        except Exception as err:
            self.err_log("close error: {}".format(err))


def reset_stdout(prefix: str | None = None):
    sys.stdout = StdoutLogTee(prefix)
