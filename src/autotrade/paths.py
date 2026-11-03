"""外部目录管理：配置、会话、数据、日志的路径解析。

打包成 exe 后，程序运行目录可能是只读的临时目录，因此 config/session/data
写到用户可写目录 %APPDATA%/autotrade/；开发环境沿用项目根目录。
"""
from __future__ import annotations

import os
import sys
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


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)
