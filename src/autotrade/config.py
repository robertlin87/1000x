"""配置加载。本地私密配置 config/config.yaml 不入库，模板见 config/config.example.yaml。

YAML 解析用 ruamel.yaml（纯 Python 模式，兼容 Python 3.15；PyYAML 无 3.15 预编译包）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")


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
    return AppConfig(
        telegram=raw.get("telegram", {}),
        exchanges=raw.get("exchanges", {}),
        risk=raw.get("risk", {}),
        analysts=raw.get("analysts", {}),
        behavior=raw.get("behavior", {}),
        notify=raw.get("notify", {}),
        storage=raw.get("storage", {}),
        dry_run=raw.get("dry_run", True),
    )
