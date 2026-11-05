"""啟動時詢問止盈部位比例，並記住使用者上次填的值。

由 scripts/run.py（start_run.bat）在 main.run() 之前調用，首次設定向導也使用。
設定欄位是 risk.tp_ratios（4 個百分比數字，加總 = 100），與 GUI 嚮導共用。

交互約定（2026-11-05 使用者指定）：
  Y / 回車 → 沿用目前比例，直接開始監聽
  N / ESC  → 逐檔輸入新比例；空回車 = 該檔為 0（4 檔都要問完）；
             4 檔全空 = 等同取消（保留原值）；任一檔 ESC = 取消
"""
from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML

from .cli_io import (
    is_interactive as _is_interactive,
    read_key as _read_key,
    read_text as _read_text,
)
from .config import DEFAULT_TP_RATIOS, is_plain_number, parse_tp_ratios

_ACCEPT_KEYS = (b"\r", b"\n", b"y", b"Y")
_MODIFY_KEYS = (b"n", b"N", b"\x1b")  # \x1b = ESC

_N_TIERS = 4

DEFAULT = list(DEFAULT_TP_RATIOS)  # 預設 25/25/25/25（單一事實源：config.DEFAULT_TP_RATIOS）


def read_tp_ratios(config_path: str | Path) -> list[float]:
    """讀目前止盈部位比例；設定不存在或值非法時回退預設 25/25/25/25。"""
    path = Path(config_path)
    if not path.exists():
        return list(DEFAULT)
    try:
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f) or {}
        return parse_tp_ratios(
            (data.get("risk") or {}).get("tp_ratios", DEFAULT)
        )
    except (OSError, ValueError, AttributeError, TypeError):
        return list(DEFAULT)


def save_tp_ratios(config_path: str | Path, ratios: list[float]) -> None:
    """把新比例寫回 config.yaml（round-trip 模式，保留註釋與其他欄位）。"""
    path = Path(config_path)
    yaml = YAML()
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f) or {}
    if data.get("risk") is None:
        data["risk"] = {}
    data["risk"]["tp_ratios"] = [float(v) for v in ratios]
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def format_tp_ratios(ratios: list[float]) -> str:
    """格式化顯示：25% / 25% / 25% / 25%（:g 去掉多餘的 .0）。"""
    return " / ".join(f"{v:g}%" for v in ratios)


def read_tp_ratios_input(current: list[float]) -> list[float] | None:
    """逐檔輸入 4 個比例數字（空回車 = 該檔為 0），返回完整 4 元素列表或 None。

    規則（使用者 2026-11-05）：
    - 任一檔按 ESC → None（取消修改）
    - 4 檔全部空回車 → 返回 list(current)（等同取消，保留原值）
    - 填了任意數字即啟動修改：4 檔（未填視為 0）加總必須 = 100，否則整輪重填
    """
    print("  填寫數字即可，不用填 % 符號（例如 25% 就填 25）；可填 0；直接回車 = 該檔為 0")
    while True:
        raw: list[str] = []
        for i in range(1, _N_TIERS + 1):
            val = _read_text(f"  請輸入 TP{i} 的部位比例：", allow_esc=True)
            if val is None:  # ESC
                return None
            raw.append(val.strip())
        if all(v == "" for v in raw):
            return list(current)
        entries = [v if v != "" else "0" for v in raw]
        if not all(is_plain_number(v) for v in entries):
            print("  只能填數字，請重新輸入。")
            continue
        try:
            return parse_tp_ratios(entries)
        except ValueError:
            print("  必須加起來等於 100%，請重新輸入。")


def prompt_tp_ratios(config_path: str | Path) -> list[float]:
    """顯示目前比例並按鍵決定是否修改，返回本次使用的比例。

    非交互環境（stdin 不是 tty，如被腳本重定向）直接沿用目前值，避免卡住。
    """
    current = read_tp_ratios(config_path)
    print("=" * 46)
    print(f"  目前止盈部位比例：{format_tp_ratios(current)}")
    print("=" * 46)
    print("  [Y / 回車] 沿用這個比例，直接開始監聽")
    print("  [N / ESC ] 輸入新的止盈部位比例")
    sys.stdout.flush()

    if not _is_interactive():
        return current

    while True:
        key = _read_key()
        if key in _ACCEPT_KEYS:
            print(f"  沿用止盈部位比例 {format_tp_ratios(current)}，開始監聽…\n")
            return current
        if key in _MODIFY_KEYS:
            print()
            while True:
                vals = read_tp_ratios_input(current)
                if vals is None:
                    print("  已取消修改，沿用止盈部位比例。")
                    return current
                if vals == current:
                    print("  未輸入，止盈部位比例保持不變，開始監聽…\n")
                    return current
                save_tp_ratios(config_path, vals)
                print(f"  已儲存止盈部位比例 {format_tp_ratios(vals)}，開始監聽…\n")
                return vals
        print("  請按 Y、N、回車或 ESC")
