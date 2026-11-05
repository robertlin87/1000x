"""交易所適配層抽象。

ccxt 統一引擎：下單/改單/平倉邏輯只寫一遍，換交易所只換實現與設定。
Bitunix 若 ccxt 不支持則手寫 REST 實現同一接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class NewOrder:
    symbol: str
    side: str                   # "buy" | "sell"
    order_type: str             # "market" | "limit"
    qty: float
    price: float | None = None  # 限價單必填
    sl_price: float | None = None
    tp_prices: list[float] = field(default_factory=list)
    tp_ratios: list[float] = field(default_factory=list)
    leverage: int = 10
    reduce_only: bool = False


class ExchangeAdapter(ABC):
    """交易所能力抽象。所有方法異步，異常語義統一（失敗拋異常由上層降級處理）。"""

    @property
    @abstractmethod
    def capabilities(self) -> dict:
        """能力標記，如 {"supports_attached_sl": True}。"""

    @abstractmethod
    async def fetch_equity(self) -> float:
        """總權益（USDT）。"""

    @abstractmethod
    async def fetch_market(self, symbol: str) -> dict:
        """市場信息，必須含 contractSize（合約倍數 = 每張合約的幣數）。"""

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> float:
        """最新成交價（訂單修改重掛 TP 時的有效性守衛）。"""

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

    @abstractmethod
    async def create_order(self, o: NewOrder) -> str:
        """開倉（含 SL/TP 掛載，視 capabilities 決定隨單附帶或後掛）。返回 order_id。"""

    @abstractmethod
    async def attach_sl_tp(
        self,
        order_id: str,
        symbol: str,
        sl: float | None,
        tps: list[tuple[float, float]] | None,  # [(價格, 數量), ...] reduce-only
    ) -> None: ...

    @abstractmethod
    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """改單：移動保本/移動止損靠改 SL 單實現。"""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> None: ...

    @abstractmethod
    async def cancel_all_for_symbol(self, symbol: str) -> None:
        """終態清理：SL 或最終 TP 觸發 / 手工平倉 → 撤該 symbol 全部掛單。"""

    @abstractmethod
    async def fetch_position(self, symbol: str) -> dict | None: ...

    @abstractmethod
    async def fetch_all_positions(self) -> list[dict]:
        """全部持倉（內部 symbol 格式），用於風控與看護對賬。

        [{symbol, side, qty, entry_price, sl_price}, ...]，無持倉返回 []。
        """

    @abstractmethod
    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]: ...
