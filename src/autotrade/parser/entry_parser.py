"""报单解析器：按 config/templates/entry.yaml 行级模板解析统一格式报单。

行级匹配：header 必须命中；各字段按模板在正文（截去「操作記錄」段）逐项搜索。
结构完整性（header + 进场价 + SL + ≥1 TP）不满足则返回 None。
语义校验（做空 TP < entry < SL、风控行存在等）由 validate() 给出告警——
M1 dry-run 只记告警，硬 reject 由 M2 风控层负责，保证不丢信号。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "config" / "templates"


@dataclass(slots=True)
class Signal:
    order_id: str
    symbol: str            # 原始符号，如 LITUSDT
    side: str              # "long" | "short"
    entry: float
    is_limit: bool         # True=掛單，False=現價
    leverage: int
    sl: float
    tps: list[float] = field(default_factory=list)
    margin_pct: float = 0.0    # 保證金%（占总本金，可带上限）
    risk_pct: float = 0.0      # 風控行「控倉維持 x%」
    stop_dist_pct: float = 0.0  # 風控行「止損距離 x%」
    analyst: str = ""
    raw_text: str = ""


class EntryParser:
    """加载 entry.yaml 模板，逐行匹配组装 Signal。"""

    def __init__(self, templates_dir: Path | None = None) -> None:
        path = (templates_dir or TEMPLATES_DIR) / "entry.yaml"
        with open(path, encoding="utf-8") as f:
            tpl = _yaml.load(f)
        self._header = re.compile(tpl["header"])
        self._fields: dict[str, re.Pattern] = {
            name: re.compile(rx) for name, rx in tpl["fields"].items()
        }
        self._ops_header = re.compile(tpl["ops_header"])

    def extract_order_id(self, text: str) -> str | None:
        """仅提取订单号（编辑消息解析失败时的兜底）。"""
        m = self._header.search(text)
        return m.group("order_id") if m else None

    def parse(self, text: str) -> Signal | None:
        m = self._header.search(text)
        if not m:
            return None
        # 操作記錄段交给 op_parser，字段只在报单正文里找
        body = self._ops_header.split(text, maxsplit=1)[0]
        signal = Signal(
            order_id=m.group("order_id"),
            symbol=f"{m.group('symbol')}USDT",
            side="long" if "做多" in m.group("side") else "short",
            entry=0.0,
            is_limit=False,
            leverage=0,
            sl=0.0,
            raw_text=text,
        )

        tp_pairs: list[tuple[int, float]] = []
        for name, rx in self._fields.items():
            if name == "tp":
                for tm in rx.finditer(body):
                    tp_pairs.append((int(tm.group("tp_index")),
                                     float(tm.group("price").replace(",", ""))))
                continue
            fm = rx.search(body)
            if not fm:
                continue
            g = fm.groupdict()
            if name == "entry":
                signal.entry = float(g["entry"].replace(",", ""))
                signal.is_limit = g["is_limit"] == "掛單"
            elif name == "leverage":
                signal.leverage = int(g["leverage"])
            elif name == "margin":
                signal.margin_pct = float(g["margin_pct"])
            elif name == "sl":
                signal.sl = float(g["price"].replace(",", ""))
            elif name == "risk":
                signal.stop_dist_pct = float(g["stop_dist_pct"])
                signal.risk_pct = float(g["risk_pct"])
            elif name == "analyst":
                signal.analyst = g["analyst"].strip()
        signal.tps = [p for _, p in sorted(tp_pairs)]

        # 结构完整性：缺进场/SL/TP 视为解析失败（交给 LLM 兜底或 unknown）
        if signal.entry <= 0 or signal.sl <= 0 or not signal.tps:
            return None
        return signal

    def validate(self, s: Signal) -> list[str]:
        """语义校验，返回告警列表（空 = 通过）。硬 reject 在 M2 风控层。"""
        warnings: list[str] = []
        if s.risk_pct <= 0 or s.stop_dist_pct <= 0:
            warnings.append("缺少風控行")
        if s.side == "long":
            if not all(p > s.entry for p in s.tps):
                warnings.append("做多但存在 TP ≤ 進場價")
            if s.sl >= s.entry:
                warnings.append("做多但 SL ≥ 進場價")
        else:
            if not all(p < s.entry for p in s.tps):
                warnings.append("做空但存在 TP ≥ 進場價")
            if s.sl <= s.entry:
                warnings.append("做空但 SL ≤ 進場價")
        return warnings
