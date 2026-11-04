"""文件日志：落盘到 temp 目录（轮转），是「导出问题报告」的数据来源。

temp 每日清理（paths.cleanup_temp_dir）：昨天及更早的日志在每次启动时
被删除，只保留当天；当天内按 1MB × 3 份轮转兜底。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import paths

_MARKER = "_autotrade_file_handler_installed"


def install_file_logging() -> None:
    """把日志写入 temp/autotrade.log（幂等，重复调用只挂一次）。"""
    if getattr(install_file_logging, _MARKER, False):
        return
    paths.ensure_dirs()
    handler = RotatingFileHandler(
        paths.temp_dir() / "autotrade.log",
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    setattr(install_file_logging, _MARKER, True)
