"""紧凑操作通知解析器（新消息通道）。

手工操作时会另发一条新消息（如「訂單 180 SNDKUSDT 做多 🟥 已平倉」），
同时原报单被编辑。通知与编辑两通道互为备份，统一事件层幂等去重。
规则（与用户确认 2026-11-04）：
- hedge / close / modify = 指令要执行（套保移损、手工平仓、訂單修改）
- tp_hit / all_tp / sl_hit = 全平或部分平仓的告知；全平场景撤残留挂单，
  TP1-3 部分平仓不动作
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from .op_parser import _extract_ts, parse_modify_fields

_yaml = YAML(typ="safe")

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "config" / "templates"


@dataclass(slots=True)
class NoticeEvent:
    order_id: str
    symbol: str
    side: str              # "long" | "short"
    action_type: str       # close | hedge | tp_hit | all_tp | sl_hit | modify
    tp_index: int | None = None
    price: float | None = None
    mod_fields: dict | None = None   # modify：{"entry", "tps", "sl"}
    ts_text: str = ""
    raw_text: str = ""


class NoticeParser:
    """按 notice.yaml 匹配；返回 None 表示不是通知消息。"""

    def __init__(self, templates_dir: Path | None = None) -> None:
        path = (templates_dir or TEMPLATES_DIR) / "notice.yaml"
        with open(path, encoding="utf-8") as f:
            tpl = _yaml.load(f)
        self._templates = [
            (t["action_type"], re.compile(t["regex"])) for t in tpl["templates"]
        ]

    def parse(self, text: str) -> NoticeEvent | None:
        for action_type, rx in self._templates:
            m = rx.search(text)
            if not m:
                continue
            g = m.groupdict()
            mod_fields = None
            if action_type == "modify":
                # 头部之后是「· 進場 X · TPn X · 止損 X」紧凑字段串
                mod_fields = parse_modify_fields(text)
            return NoticeEvent(
                order_id=g["order_id"],
                symbol=f"{g['symbol']}USDT",
                side="long" if g["side"] == "做多" else "short",
                action_type=action_type,
                tp_index=int(g["tp_index"]) if g.get("tp_index") else None,
                price=float(g["price"].replace(",", "")) if g.get("price") else None,
                mod_fields=mod_fields,
                ts_text=_extract_ts(text),
                raw_text=text,
            )
        return None
