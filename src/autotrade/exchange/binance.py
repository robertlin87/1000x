"""Binance 適配器：ccxt.binanceusdm（USDT-M 永續）。

TP/SL 用獨立 reduce-only 單（STOP_MARKET / 限價 TP），隨單附掛不支持。
移動止損 = 撤舊 SL 觸發單 + 按新價重掛。
"""
from __future__ import annotations

import asyncio
import logging

import ccxt

from ..proxy import resolve_proxy
from .base import ExchangeAdapter, NewOrder

log = logging.getLogger("autotrade.exchange.binance")


class BinanceAdapter(ExchangeAdapter):
    def __init__(self, api_key: str, secret: str, proxy: dict | None = None) -> None:
        if not api_key or not secret:
            raise ValueError("Binance apiKey/secret 未設定")
        ccxt_cfg: dict = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }
        resolved = resolve_proxy(proxy, default_type="http")
        if resolved:
            ptype, addr, port = resolved
            url = f"{ptype}://{addr}:{port}"
            ccxt_cfg["proxies"] = {"http": url, "https": url}
        self._ex = ccxt.binanceusdm(ccxt_cfg)
        # 看護對賬需要拉「全部」掛單（不指定 symbol）；binanceusdm 預設會把這個
        # 限速提醒當作異常拋出，顯式確認後放行。
        self._ex.options.setdefault("fetchOpenOrders", {})["warnWithoutSymbol"] = False
        self._markets_loaded = False

    @property
    def capabilities(self) -> dict:
        # TP/SL 走獨立 reduce-only 單（OrderManager 非 attached 分支）
        return {"supports_attached_sl": False}

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await asyncio.to_thread(self._ex.load_markets)
            self._markets_loaded = True

    @staticmethod
    def to_ccxt_symbol(symbol: str) -> str:
        if "/" in symbol:
            return symbol
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        return f"{base}/USDT:USDT"

    @staticmethod
    def from_ccxt_symbol(symbol: str) -> str:
        if "/" not in symbol:
            return symbol
        base, _, settle = symbol.partition("/")
        return f"{base}{settle.split(':')[0]}"

    # ---- 只讀 ----

    async def fetch_equity(self) -> float:
        await self._ensure_markets()
        bal = await asyncio.to_thread(self._ex.fetch_balance)
        usdt = bal.get("USDT") or {}
        return float(usdt.get("total") or 0)

    async def fetch_market(self, symbol: str) -> dict:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        if s not in self._ex.markets:
            raise ValueError(f"Binance 無此交易對（或已下架）：{s}")
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

    async def fetch_ticker(self, symbol: str) -> float:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        t = await asyncio.to_thread(self._ex.fetch_ticker, s)
        return float(t.get("last") or 0)

    # ---- 交易 ----

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        # 全倉模式；逐倉需改 marginMode 為 ISOLATED（實測確認預設行為後調整）
        await asyncio.to_thread(
            self._ex.set_leverage, leverage, s, {"marginMode": "CROSS"}
        )

    async def create_order(self, o: NewOrder) -> str:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(o.symbol)
        params: dict = {}
        if o.reduce_only:
            params["reduceOnly"] = True
        res = await asyncio.to_thread(
            self._ex.create_order, s, o.order_type, o.side, o.qty, o.price, params
        )
        return str(res.get("id") or res.get("orderId") or "")

    async def attach_sl_tp(self, order_id: str, symbol: str, sl, tps) -> None:
        """掛獨立 SL：STOP_MARKET reduce-only（數量=目前持倉）。"""
        if sl is None:
            return
        await self._ensure_markets()
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("掛 SL 時無持倉：%s", symbol)
            return
        close_side = "sell" if pos["side"] == "long" else "buy"
        await asyncio.to_thread(
            self._ex.create_order, self.to_ccxt_symbol(symbol),
            "market", close_side, pos["qty"], None,
            {"stopPrice": sl, "reduceOnly": True},
        )
        log.info("已掛獨立 SL：%s @%s（qty=%s）", symbol, sl, pos["qty"])

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """移動止損 = 撤舊 SL 觸發單 + 按新價重掛（Binance 無改 SL 端點）。"""
        sl_price = kwargs.get("sl_price")
        if sl_price is None:
            raise ValueError("amend_order 需要 sl_price")
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("移動止損時無持倉：%s", symbol)
            return
        # 撤掉舊的 STOP_MARKET reduce-only 單
        open_orders = await self.fetch_open_orders(symbol)
        for o in open_orders:
            if o.get("reduce_only") and o.get("type") == "market" and o.get("stop_price"):
                await self.cancel_order(o["id"], symbol)
        close_side = "sell" if pos["side"] == "long" else "buy"
        await asyncio.to_thread(
            self._ex.create_order, s, "market", close_side, pos["qty"], None,
            {"stopPrice": sl_price, "reduceOnly": True},
        )
        log.info("已移動止損：%s SL=%s", symbol, sl_price)

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._ensure_markets()
        await asyncio.to_thread(
            self._ex.cancel_order, order_id, self.to_ccxt_symbol(symbol)
        )

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        await self._ensure_markets()
        await asyncio.to_thread(
            self._ex.cancel_all_orders, self.to_ccxt_symbol(symbol)
        )

    async def fetch_position(self, symbol: str) -> dict | None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        positions = await asyncio.to_thread(self._ex.fetch_positions, [s])
        for p in positions:
            qty = float(p.get("contracts") or 0)
            if qty != 0:
                return {
                    "symbol": self.from_ccxt_symbol(s),
                    "side": p.get("side"),
                    "qty": qty,
                    "entry_price": p.get("entryPrice"),
                    "sl_price": None,
                }
        return None

    async def fetch_all_positions(self) -> list[dict]:
        await self._ensure_markets()
        positions = await asyncio.to_thread(self._ex.fetch_positions, None)
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
                "sl_price": None,
            })
        return out

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol) if symbol else None
        orders = await asyncio.to_thread(self._ex.fetch_open_orders, s)
        return [
            {
                "id": str(o.get("id") or ""),
                "symbol": self.from_ccxt_symbol(o.get("symbol") or ""),
                "side": o.get("side"),
                "type": o.get("type"),
                "qty": o.get("amount"),
                "price": o.get("price"),
                "stop_price": o.get("stopPrice"),
                "reduce_only": o.get("reduceOnly"),
            }
            for o in orders
        ]
