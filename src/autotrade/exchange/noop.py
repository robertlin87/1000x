"""NoopAdapter：dry-run 假适配器，全链路不碰交易所（PLAN：dry-run 用 NoopAdapter）。"""
from __future__ import annotations

from .base import ExchangeAdapter, NewOrder


class NoopAdapter(ExchangeAdapter):
    def __init__(self, equity: float = 1000.0) -> None:
        self._equity = equity
        self._counter = 0
        self._positions: dict[str, dict] = {}

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": True}

    async def fetch_equity(self) -> float:
        return self._equity

    async def fetch_market(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "contractSize": 1.0,
            "precision": {"amount": 0.001, "price": 0.0001},
            "limits": {},
            "active": True,
        }

    async def fetch_ticker(self, symbol: str) -> float:
        return 1.0

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        return None

    async def create_order(self, o: NewOrder) -> str:
        self._counter += 1
        return f"noop-{self._counter}"

    async def attach_sl_tp(self, order_id: str, symbol: str, sl, tps) -> None:
        return None

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        return None

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        return None

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        return None

    async def fetch_position(self, symbol: str) -> dict | None:
        return self._positions.get(symbol)

    async def fetch_all_positions(self) -> list[dict]:
        return list(self._positions.values())

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        return []
