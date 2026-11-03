"""持仓状态机。

state ∈ {PENDING, FILLED, PARTIAL_TP, BREAKEVEN, CLOSED, CANCELED, UNKNOWN}
- 主触发（价格）：TP 档成交 / SL 触发 / 末档 TP 成交 → 撤该 symbol 其余挂单
- 备份触发（事件核对）：动作前先查交易所实际状态再决定，杜绝双卖
"""
from __future__ import annotations

from enum import StrEnum


class PositionState(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL_TP = "partial_tp"
    BREAKEVEN = "breakeven"
    CLOSED = "closed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class Position:
    """单个 symbol 的持仓状态（内存态，配合 DB positions 表持久化）。"""

    def __init__(self, symbol: str, side: str, qty: float, entry_price: float,
                 sl_price: float | None = None) -> None:
        self.symbol = symbol
        self.side = side  # "long" | "short"
        self.qty = qty
        self.entry_price = entry_price
        self.sl_price = sl_price
        self.state = PositionState.PENDING
        self.tp_hit_count = 0
        self.remaining_qty = qty


class PositionTracker:
    """按 symbol 维护持仓状态与 TP 档计数。"""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def open(self, symbol: str, side: str, qty: float, entry_price: float,
             sl_price: float | None = None) -> Position:
        p = Position(symbol, side, qty, entry_price, sl_price)
        self._positions[symbol] = p
        return p

    def get(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def all_open(self) -> list[Position]:
        return [p for p in self._positions.values()
                if p.state not in (PositionState.CLOSED, PositionState.CANCELED)]

    def mark_filled(self, symbol: str) -> None:
        p = self._positions.get(symbol)
        if p and p.state == PositionState.PENDING:
            p.state = PositionState.FILLED

    def on_tp_hit(self, symbol: str, tier_qty: float) -> None:
        p = self._positions.get(symbol)
        if not p:
            return
        p.tp_hit_count += 1
        p.remaining_qty = max(0.0, p.remaining_qty - tier_qty)
        p.state = PositionState.CLOSED if p.remaining_qty <= 0 else PositionState.PARTIAL_TP

    def on_breakeven(self, symbol: str, sl_price: float) -> None:
        p = self._positions.get(symbol)
        if p:
            p.sl_price = sl_price
            p.state = PositionState.BREAKEVEN

    def on_close(self, symbol: str) -> None:
        p = self._positions.get(symbol)
        if p:
            p.remaining_qty = 0.0
            p.state = PositionState.CLOSED

    def on_cancel(self, symbol: str) -> None:
        p = self._positions.get(symbol)
        if p:
            p.state = PositionState.CANCELED
