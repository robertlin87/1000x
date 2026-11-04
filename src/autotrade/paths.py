"""外部目录管理：配置、会话、数据、日志的路径解析。

打包成 exe 后，程序运行目录可能是只读的临时目录，因此 config/session/data
写到用户可写目录 %APPDATA%/autotrade/；开发环境沿用项目根目录。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """应用数据根目录：打包后 %APPDATA%/autotrade，开发时项目根目录。"""
    if _is_frozen():
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "autotrade"
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return app_dir() / "config"


def config_path() -> Path:
    return config_dir() / "config.yaml"


def session_path(name: str = "autotrade_session") -> str:
    """Telethon 会话文件路径（绝对路径，避免打包后写到临时目录）。"""
    return str(app_dir() / name)


def data_dir() -> Path:
    return app_dir() / "data"


def db_path() -> Path:
    return data_dir() / "autotrade.db"


def logs_dir() -> Path:
    return app_dir() / "logs"


def temp_dir() -> Path:
    """临时文件目录：日志与问题报告（源码版 = 项目根/temp；打包版 = 应用数据目录/temp）。"""
    return app_dir() / "temp"


def cleanup_temp_dir() -> None:
    """每日清理：删除 temp 内修改时间非今天的文件（只保留当天）。

    用户规则（2026-11-04）：旧日志/报告在问题解决后无意义，用户不会自己
    清理——每次启动时清掉昨天及更早的文件。
    """
    d = temp_dir()
    if not d.exists():
        return
    today = datetime.now().date()
    for f in d.iterdir():
        if not f.is_file():
            continue
        try:
            mdate = datetime.fromtimestamp(f.stat().st_mtime).date()
        except OSError:
            continue
        if mdate < today:
            try:
                f.unlink()
            except OSError:
                pass


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), logs_dir(), temp_dir()):
        d.mkdir(parents=True, exist_ok=True)
