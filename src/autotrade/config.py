"""設定加載。本地私密設定 config/config.yaml 不入庫，模板見 config/config.example.yaml。

YAML 解析用 ruamel.yaml（純 Python 模式，兼容 Python 3.15；PyYAML 無 3.15 預編譯包）。
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

log = logging.getLogger("autotrade.config")

_MULTIPLIER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")

# 止盈部位比例預設值：四檔各 25%（數字為百分號前的值，加總必須等於 100）
DEFAULT_TP_RATIOS: tuple[float, ...] = (25.0, 25.0, 25.0, 25.0)
_TP_RATIO_SUM_TOL = 0.01


def is_plain_number(text: str) -> bool:
    """純數字字串（整數或小數，無正負號/科學計數法/全角），供輸入層前置判斷。"""
    return bool(_MULTIPLIER_RE.fullmatch(str(text).strip()))


def parse_multiplier(value: object) -> float:
    """解析下單倍數：只接受大於 0 的整數或小數（純數字），返回 float。

    嚮導輸入框與 config.yaml 共用此校驗，避免非法值等到收到報單才炸。
    科學計數法、正負號、文字、全角數字一律拒絕。
    """
    text = str(value).strip()
    if not _MULTIPLIER_RE.fullmatch(text):
        raise ValueError("下單倍數只能是數字（整數或小數）")
    num = float(text)
    if not math.isfinite(num) or num <= 0:
        raise ValueError("下單倍數必須是大於 0 的數字")
    return num


def parse_tp_ratios(value: object) -> list[float]:
    """解析止盈部位比例：4 個百分比數字，加總必須等於 100。

    - "equal"（舊版佔位值，大小寫不敏感）→ 遷移為預設均分 [25, 25, 25, 25]
    - 4 元素序列（數字或數字字串）→ 每項 ≥ 0、isfinite、加總 = 100（容差 0.01）
    與 parse_multiplier 相同：科學計數法、正負號、文字、全角數字、帶 % 一律拒絕。
    允許 0（該檔不掛單）；單項無需上界（加總 = 100 已隱含）。
    """
    if isinstance(value, str):
        if value.strip().lower() == "equal":
            return list(DEFAULT_TP_RATIOS)
        raise ValueError("止盈部位比例必須是 4 個數字（例如 [25, 25, 25, 25]）")
    if value is None or isinstance(value, (int, float)):
        raise ValueError("止盈部位比例必須是 4 個數字（例如 [25, 25, 25, 25]）")
    try:
        items = list(value)
    except TypeError:
        raise ValueError("止盈部位比例必須是 4 個數字（例如 [25, 25, 25, 25]）") from None
    if len(items) != 4:
        raise ValueError(f"止盈部位比例必須是 4 個數字（目前 {len(items)} 個）")
    out: list[float] = []
    for item in items:
        text = str(item).strip()
        if not _MULTIPLIER_RE.fullmatch(text):
            raise ValueError("止盈部位比例只能填數字（整數或小數）")
        num = float(text)
        if not math.isfinite(num) or num < 0:
            raise ValueError("止盈部位比例必須是大於等於 0 的數字")
        out.append(num)
    if abs(sum(out) - 100.0) > _TP_RATIO_SUM_TOL:
        raise ValueError("四檔比例加起來必須等於 100%")
    return out


@dataclass(slots=True)
class AppConfig:
    telegram: dict
    exchanges: dict
    risk: dict
    analysts: dict
    behavior: dict
    notify: dict
    storage: dict
    dry_run: bool = True


def load_config(path: str) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        raw = _yaml.load(f) or {}
    risk = dict(raw.get("risk") or {})
    if "order_multiplier" in risk:
        risk["order_multiplier"] = parse_multiplier(risk["order_multiplier"])
    # 止盈部位比例規範化：缺失自動注入、"equal" 舊值遷移、非法回退預設均分。
    # 與 order_multiplier 的「非法即拒」不同：均分是安全預設（= 舊行為），不卡啟動。
    try:
        risk["tp_ratios"] = parse_tp_ratios(risk.get("tp_ratios", DEFAULT_TP_RATIOS))
    except ValueError as e:
        log.warning("risk.tp_ratios 設定無效，回退預設均分 25/25/25/25：%s", e)
        risk["tp_ratios"] = list(DEFAULT_TP_RATIOS)
    return AppConfig(
        telegram=raw.get("telegram", {}),
        exchanges=raw.get("exchanges", {}),
        risk=risk,
        analysts=raw.get("analysts", {}),
        behavior=raw.get("behavior", {}),
        notify=raw.get("notify", {}),
        storage=raw.get("storage", {}),
        dry_run=raw.get("dry_run", True),
    )
