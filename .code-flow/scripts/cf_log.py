#!/usr/bin/env python3
# -*- encoding=utf-8 -*-
import datetime
import io
import os
import sys


LOG_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../logs"))
os.makedirs(LOG_ROOT, exist_ok=True)

_log_path = None


def get_log_path(prefix):
    try:
        if not prefix or not isinstance(prefix, str):
            log_path = os.path.join(LOG_ROOT, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
        log_path = os.path.join(LOG_ROOT, prefix, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    except Exception as e:
        raise e
    return log_path


class LogTee:
    def __init__(self, stream, filepath):
        self._stream = stream
        self._file = open(filepath, "w", encoding="utf-8")

    def write(self, data):
        self._stream.write(data)
        self._file.write(data)

    def flush(self):
        self._stream.flush()
        self._file.flush()

    def close(self):
        self._file.close()


def reset_stdout(prefix=None):
    """
    重建 stdout
    :param prefix:
    :return:
    """
    global _log_path
    _log_path = get_log_path(prefix)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stdout = LogTee(sys.stdout, _log_path)


def cleanup_none_logfile():
    """
    清理空的日志文件
    """
    global _log_path
    if _log_path and isinstance(_log_path, str):
        try:
            if not os.path.isfile(_log_path):
                return
            with open(_log_path, "r") as f:
                content = f.read().strip()
            if not content:
                os.remove(_log_path)
        except Exception:
            pass
