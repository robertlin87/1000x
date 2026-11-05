"""檔案日誌：落盤到 temp 目錄（輪轉），是「導出問題報告」的數據來源。

temp 每日清理（paths.cleanup_temp_dir）：昨天及更早的日誌在每次啟動時
被刪除，只保留當天；當天內按 1MB × 3 份輪轉兜底。
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from . import paths

_MARKER = "_autotrade_file_handler_installed"

# 本機網絡連線細節不寫進使用者可見視窗/問題報告：第三方庫（Telethon、
# ccxt、requests）連線失敗時會把地址和端口原樣打進 WARNING 日誌。
_LOCAL_ADDR = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\]):\d+")
_NETWORK_WORDS = ("proxy", "代理", "vpn", "socks5", "clash", "v2ray", "翻牆", "被牆")


def scrub_network_words(text: str) -> str:
    """替換本機網絡連線細節，供日誌過濾與問題報告讀取歷史日誌共用。"""
    clean = _LOCAL_ADDR.sub("[network]", text)
    for word in _NETWORK_WORDS:
        clean = re.sub(re.escape(word), "network", clean, flags=re.IGNORECASE)
    return clean


class PrivacyFilter(logging.Filter):
    """脫敏日誌裡的本機網絡連線細節，保留其餘診斷信息。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.name = re.sub("proxy", "network", record.name, flags=re.IGNORECASE)
        msg = record.getMessage()
        low = msg.lower()
        if any(w in low for w in _NETWORK_WORDS) or _LOCAL_ADDR.search(msg):
            record.msg = scrub_network_words(msg)
            record.args = ()
        return True


def install_file_logging() -> None:
    """把日誌寫入 temp/autotrade.log（冪等，重複調用只掛一次）。"""
    if getattr(install_file_logging, _MARKER, False):
        return
    paths.ensure_dirs()
    privacy = PrivacyFilter()
    handler = RotatingFileHandler(
        paths.temp_dir() / "autotrade.log",
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(privacy)
    root = logging.getLogger()
    # basicConfig 建的控制檯 handler（BAT 視窗）同樣要脫敏
    for h in root.handlers:
        h.addFilter(privacy)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    setattr(install_file_logging, _MARKER, True)
