"""外部目錄管理：設定、會話、數據、日誌的路徑解析。

打包成 exe 後，程序運行目錄可能是隻讀的臨時目錄，因此 config/session/data
寫到使用者可寫目錄 %APPDATA%/autotrade/；開發環境沿用項目根目錄。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """應用數據根目錄：打包後 %APPDATA%/autotrade，開發時項目根目錄。"""
    if _is_frozen():
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "autotrade"
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return app_dir() / "config"


def config_path() -> Path:
    return config_dir() / "config.yaml"


def session_path(name: str = "autotrade_session") -> str:
    """Telethon 會話檔案路徑（絕對路徑，避免打包後寫到臨時目錄）。"""
    return str(app_dir() / name)


def data_dir() -> Path:
    return app_dir() / "data"


def db_path() -> Path:
    return data_dir() / "autotrade.db"


def logs_dir() -> Path:
    return app_dir() / "logs"


def temp_dir() -> Path:
    """臨時檔案目錄：日誌與問題報告（原始碼版 = 項目根/temp；打包版 = 應用數據目錄/temp）。"""
    return app_dir() / "temp"


def cleanup_temp_dir() -> None:
    """每日清理：刪除 temp 內修改時間非今天的檔案（只保留當天）。

    使用者規則（2026-11-04）：舊日誌/報告在問題解決後無意義，使用者不會自己
    清理——每次啟動時清掉昨天及更早的檔案。
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
