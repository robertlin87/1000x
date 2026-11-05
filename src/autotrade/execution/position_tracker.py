"""持倉狀態機。

state ∈ {PENDING, FILLED, PARTIAL_TP, BREAKEVEN, CLOSED, CANCELED, UNKNOWN}
- 主觸發（價格）：TP 檔成交 / SL 觸發 / 末檔 TP 成交 → 撤該 symbol 其餘掛單
- 備份觸發（事件核對）：動作前先查交易所實際狀態再決定，杜絕雙賣
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
    """單個 symbol 的持倉狀態（內存態，配合 DB positions 表持久化）。"""

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
    """按 symbol 維護持倉狀態與 TP 檔計數。"""

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
