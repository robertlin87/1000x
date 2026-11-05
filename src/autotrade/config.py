"""設定加載。本地私密設定 config/config.yaml 不入庫，模板見 config/config.example.yaml。

YAML 解析用 ruamel.yaml（純 Python 模式，兼容 Python 3.15；PyYAML 無 3.15 預編譯包）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

_MULTIPLIER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


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
