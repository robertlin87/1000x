"""交易所适配层抽象。

ccxt 统一引擎：下单/改单/平仓逻辑只写一遍，换交易所只换实现与配置。
Bitunix 若 ccxt 不支持则手写 REST 实现同一接口。
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
    price: float | None = None  # 限价单必填
    sl_price: float | None = None
    tp_prices: list[float] = field(default_factory=list)
    tp_ratios: list[float] = field(default_factory=list)
    leverage: int = 10
    reduce_only: bool = False


class ExchangeAdapter(ABC):
    """交易所能力抽象。所有方法异步，异常语义统一（失败抛异常由上层降级处理）。"""

    @property
    @abstractmethod
    def capabilities(self) -> dict:
        """能力标记，如 {"supports_attached_sl": True}。"""

    @abstractmethod
    async def fetch_equity(self) -> float:
        """总权益（USDT）。"""

    @abstractmethod
    async def fetch_market(self, symbol: str) -> dict:
        """市场信息，必须含 contractSize（合约倍数 = 每张合约的币数）。"""

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> float:
        """最新成交价（訂單修改重挂 TP 时的有效性守卫）。"""

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

    @abstractmethod
    async def create_order(self, o: NewOrder) -> str:
        """开仓（含 SL/TP 挂载，视 capabilities 决定随单附带或后挂）。返回 order_id。"""

    @abstractmethod
    async def attach_sl_tp(
        self,
        order_id: str,
        symbol: str,
        sl: float | None,
        tps: list[tuple[float, float]] | None,  # [(价格, 数量), ...] reduce-only
    ) -> None: ...

    @abstractmethod
    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """改单：移动保本/移动止损靠改 SL 单实现。"""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> None: ...

    @abstractmethod
    async def cancel_all_for_symbol(self, symbol: str) -> None:
        """终态清理：SL 或最终 TP 触发 / 手工平仓 → 撤该 symbol 全部挂单。"""

    @abstractmethod
    async def fetch_position(self, symbol: str) -> dict | None: ...

    @abstractmethod
    async def fetch_all_positions(self) -> list[dict]:
        """全部持仓（内部 symbol 格式），用于风控与看护对账。

        [{symbol, side, qty, entry_price, sl_price}, ...]，无持仓返回 []。
        """

    @abstractmethod
    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]: ...
