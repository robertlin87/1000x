"""啟動時詢問風險乘數（下單倍數），並記住使用者上次填的值。

由 scripts/run.py（start_run.bat）在 main.run() 之前調用。
設定欄位仍是 risk.order_multiplier，與 GUI 嚮導共用同一個值。

交互約定（2026-11-04 使用者指定）：
  Y / 回車  → 沿用目前值，直接開始監聽
  N / ESC   → 輸入新數字，儲存後開始監聽
首次啟動預設 1，之後每次啟動的預設值為使用者上次填的數字。
"""
from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML

from .cli_io import (
    is_interactive as _is_interactive,
    read_key as _read_key,
    read_line as _read_line,
)
from .config import parse_multiplier

DEFAULT = 1.0

_ACCEPT_KEYS = (b"\r", b"\n", b"y", b"Y")
_MODIFY_KEYS = (b"n", b"N", b"\x1b")  # \x1b = ESC


def read_multiplier(config_path: str | Path) -> float:
    """讀目前風險乘數；設定不存在或值非法時回退預設 1.0。"""
    path = Path(config_path)
    if not path.exists():
        return DEFAULT
    try:
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f) or {}
        raw = (data.get("risk") or {}).get("order_multiplier", DEFAULT)
        return parse_multiplier(raw)
    except (OSError, ValueError, AttributeError, TypeError):
        return DEFAULT


def save_multiplier(config_path: str | Path, value: float) -> None:
    """把新乘數寫回 config.yaml（round-trip 模式，保留註釋與其他欄位）。"""
    path = Path(config_path)
    yaml = YAML()
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f) or {}
    if data.get("risk") is None:
        data["risk"] = {}
    data["risk"]["order_multiplier"] = float(value)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def prompt_multiplier(config_path: str | Path) -> float:
    """顯示目前乘數並按鍵決定是否修改，返回本次使用的乘數。

    非交互環境（stdin 不是 tty，如被腳本重定向）直接沿用目前值，避免卡住。
    """
    current = read_multiplier(config_path)
    print("=" * 46)
    print(f"  目前風險乘數：{current:g}")
    print("=" * 46)
    print("  [Y / 回車] 沿用這個值，直接開始監聽")
    print("  [N / ESC ] 輸入新的風險乘數")
    sys.stdout.flush()

    if not _is_interactive():
        return current

    while True:
        key = _read_key()
        if key in _ACCEPT_KEYS:
            print(f"  沿用風險乘數 {current:g}，開始監聽…\n")
            return current
        if key in _MODIFY_KEYS:
            print()
            while True:
                raw = _read_line("  請輸入新的風險乘數（只能填數字，如 1 / 0.2 / 1.5）：").strip()
                try:
                    value = parse_multiplier(raw)
                except ValueError as e:
                    print(f"  輸入無效：{e}，請重新輸入")
                    continue
                save_multiplier(config_path, value)
                print(f"  已儲存風險乘數 {value:g}，開始監聽…\n")
                return value
        print("  請按 Y、N、回車或 ESC")
