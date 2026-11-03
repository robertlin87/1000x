"""Bybit 适配器（MVP）：ccxt.bybit 封装，USDT 永续（线性合约）+ 统一账户（UTA）。

真实验证过的要点（2026-11-02）：
- ccxt unified symbol 格式为 `BASE/USDT:USDT`（不是 BASEUSDT）
- 余额/权益在 UNIFIED 账户的 totalEquity 字段；coin 列表可能为空（未充值/无币）
- 合约倍数 contractSize 对多数山寨币为 1.0
- set_leverage / 下单 / 查持仓挂单需带 accountType=UNIFIED（ccxt 大部分自动处理）
- 随单附 SL/TP：单档用 create_order 的 stopLossPrice/takeProfitPrice；多档 TP 用
  reduce-only 限价单（由 OrderManager 编排，本适配器只提供原子操作）
"""
from __future__ import annotations

import asyncio
import logging

import ccxt

from ..proxy import resolve_proxy
from .base import ExchangeAdapter, NewOrder

log = logging.getLogger("autotrade.exchange.bybit")


# 现货 symbol 名 → Bybit USDT 永续 symbol 名（个别币两者不同名）。
# 例：PUMP 现货 / PUMPFUN 永续；同名币（如 MNT、LIT）无需映射。
# 遇到报单币在 Bybit 永续找不到时，先查这里是否需要加映射。
_SYMBOL_ALIASES = {
    "PUMP": "PUMPFUN",
}
_SYMBOL_ALIASES_REVERSE = {v: k for k, v in _SYMBOL_ALIASES.items()}


class BybitAdapter(ExchangeAdapter):
    def __init__(self, api_key: str, secret: str, testnet: bool = False,
                 proxy: dict | None = None) -> None:
        if not api_key or not secret:
            raise ValueError("Bybit apiKey/secret 未配置")
        ccxt_cfg: dict = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},  # USDT 永续（线性合约）
        }
        # 大陆直连超时/被墙：自动检测系统代理（或 config 显式指定）
        resolved = resolve_proxy(proxy, default_type="http")
        if resolved:
            ptype, addr, port = resolved
            url = f"{ptype}://{addr}:{port}"
            ccxt_cfg["proxies"] = {"http": url, "https": url}
        self._ex = ccxt.bybit(ccxt_cfg)
        if testnet:
            self._ex.set_sandbox_mode(True)
        self._markets_loaded = False

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": True}

    # ---- 工具 ----

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await asyncio.to_thread(self._ex.load_markets)
            self._markets_loaded = True

    @staticmethod
    def to_ccxt_symbol(symbol: str) -> str:
        """内部 symbol（如 LITUSDT）→ ccxt unified（LIT/USDT:USDT）。

        个别币在 Bybit 的现货名与永续名不同（如 PUMP 现货 / PUMPFUN 永续），
        经 _SYMBOL_ALIASES 映射到正确的永续名。
        """
        if "/" in symbol:
            return symbol
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        base = _SYMBOL_ALIASES.get(base, base)
        return f"{base}/USDT:USDT"

    @staticmethod
    def from_ccxt_symbol(symbol: str) -> str:
        """ccxt unified（INJ/USDT:USDT）→ 内部 symbol（INJUSDT），含别名反向映射。"""
        if "/" not in symbol:
            return symbol
        base, _, settle = symbol.partition("/")
        quote = settle.split(":")[0]
        base = _SYMBOL_ALIASES_REVERSE.get(base, base)
        return f"{base}{quote}"

    # ---- 只读 ----

    async def fetch_equity(self) -> float:
        await self._ensure_markets()
        bal = await asyncio.to_thread(self._ex.fetch_balance, {"accountType": "UNIFIED"})
        info = bal.get("info") or {}
        lst = (info.get("result") or {}).get("list") or []
        if lst:
            return float(lst[0].get("totalEquity") or 0)
        return 0.0

    async def fetch_market(self, symbol: str) -> dict:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        if s not in self._ex.markets:
            raise ValueError(f"Bybit 无此交易对（或已下架）：{s}")
        m = self._ex.markets[s]
        return {
            "symbol": s,
            "contractSize": m.get("contractSize", 1.0),
            "precision": {
                "amount": m.get("precision", {}).get("amount"),
                "price": m.get("precision", {}).get("price"),
            },
            "limits": m.get("limits", {}),
            "active": m.get("active", True),
        }

    # ---- 交易 ----

    async def fetch_ticker(self, symbol: str) -> float:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        t = await asyncio.to_thread(self._ex.fetch_ticker, s)
        return float(t.get("last") or 0)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        try:
            await asyncio.to_thread(
                self._ex.set_leverage, leverage, s, {"accountType": "UNIFIED"}
            )
        except ccxt.BadRequest as e:
            # Bybit 110043「leverage not modified」= 杠杆已是目标值，幂等成功
            msg = str(e)
            if "leverage not modified" in msg or "110043" in msg:
                log.info("杠杆已是 %sx（幂等跳过）：%s", leverage, symbol)
                return
            raise

    async def create_order(self, o: NewOrder) -> str:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(o.symbol)
        params: dict = {}
        if o.reduce_only:
            params["reduceOnly"] = True
        if o.sl_price is not None:
            # 用 attached stopLoss（tpslMode），Bybit 按持仓方向自动判 triggerDirection；
            # 若用 stopLossPrice 会走 trigger-order 分支，方向判断错误（110092）
            params["stopLoss"] = o.sl_price
        # 单档 TP 随单附；多档 TP 由 OrderManager 用 reduce-only 限价单实现
        if not o.reduce_only and len(o.tp_prices) == 1:
            params["takeProfit"] = o.tp_prices[0]
        res = await asyncio.to_thread(
            self._ex.create_order, s, o.order_type, o.side, o.qty, o.price, params
        )
        return str(res.get("id") or res.get("orderId") or "")

    async def attach_sl_tp(self, order_id: str, symbol: str, sl, tps) -> None:
        # Bybit 支持随单附 SL/TP（supports_attached_sl=True），开仓已带 SL；
        # 多档 TP 由 OrderManager 用 reduce-only 限价单实现，不经过这里。
        return None

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """移动止损：改持仓 SL。

        ccxt 的 bybit 没有 set_stop_loss；改持仓止损走 /v5/position/trading-stop
        端点（create_order + tradingStopEndpoint=True + stopLossPrice），
        该端点按持仓方向自动判断触发方向，无需 triggerDirection。
        """
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        sl_price = kwargs.get("sl_price")
        if sl_price is None:
            raise ValueError("amend_order 需要 sl_price")
        await asyncio.to_thread(
            self._ex.create_order, s, "market", "buy", None, None,
            {
                "stopLossPrice": sl_price,
                "tradingStopEndpoint": True,
                "accountType": "UNIFIED",
            },
        )

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        await asyncio.to_thread(
            self._ex.cancel_order, order_id, s, {"accountType": "UNIFIED"}
        )

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        await asyncio.to_thread(
            self._ex.cancel_all_orders, s,
            {"accountType": "UNIFIED", "category": "linear"},
        )

    async def fetch_position(self, symbol: str) -> dict | None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        positions = await asyncio.to_thread(
            self._ex.fetch_positions, [s],
            {"accountType": "UNIFIED", "category": "linear"},
        )
        for p in positions:
            qty = float(p.get("contracts") or 0)
            if qty != 0:
                return {
                    "symbol": self.from_ccxt_symbol(s),
                    "side": p.get("side"),
                    "qty": qty,
                    "entry_price": p.get("entryPrice"),
                    "sl_price": p.get("stopLossPrice"),
                    "tp_price": p.get("takeProfitPrice"),
                }
        return None

    async def fetch_all_positions(self) -> list[dict]:
        """全部持仓（内部 symbol 格式），风控与看护对账的数据源。"""
        await self._ensure_markets()
        positions = await asyncio.to_thread(
            self._ex.fetch_positions, None,
            {"accountType": "UNIFIED", "category": "linear"},
        )
        out: list[dict] = []
        for p in positions:
            qty = float(p.get("contracts") or 0)
            if qty == 0:
                continue
            out.append({
                "symbol": self.from_ccxt_symbol(p.get("symbol") or ""),
                "side": p.get("side"),
                "qty": qty,
                "entry_price": p.get("entryPrice"),
                "sl_price": p.get("stopLossPrice"),
            })
        return out

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol) if symbol else None
        params = {"accountType": "UNIFIED", "category": "linear"}
        orders = await asyncio.to_thread(
            self._ex.fetch_open_orders, s, None, None, params
        )
        return [
            {
                "id": str(o.get("id") or o.get("orderId") or ""),
                "symbol": self.from_ccxt_symbol(o.get("symbol") or ""),
                "side": o.get("side"),
                "type": o.get("type"),
                "qty": o.get("amount"),
                "price": o.get("price"),
                "reduce_only": o.get("reduceOnly"),
            }
            for o in orders
        ]
