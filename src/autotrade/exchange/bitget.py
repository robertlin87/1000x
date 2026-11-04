"""Bitget 适配器：ccxt.bitget（USDT-M 永续，统一账户 UTA）。

passphrase 必填（ccxt 的 password 参数）。TP/SL 走独立 reduce-only
触发单（plan order）；移动止损 = 撤旧触发单 + 重挂。
"""
from __future__ import annotations

import asyncio
import logging

import ccxt

from ..proxy import resolve_proxy
from .base import ExchangeAdapter, NewOrder

log = logging.getLogger("autotrade.exchange.bitget")


class BitgetAdapter(ExchangeAdapter):
    def __init__(self, api_key: str, secret: str, passphrase: str = "",
                 proxy: dict | None = None) -> None:
        if not api_key or not secret or not passphrase:
            raise ValueError("Bitget apiKey/secret/passphrase 均必填")
        ccxt_cfg: dict = {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,  # ccxt 的 password 字段 = Bitget passphrase
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
        resolved = resolve_proxy(proxy, default_type="http")
        if resolved:
            ptype, addr, port = resolved
            url = f"{ptype}://{addr}:{port}"
            ccxt_cfg["proxies"] = {"http": url, "https": url}
        self._ex = ccxt.bitget(ccxt_cfg)
        self._markets_loaded = False

    @property
    def capabilities(self) -> dict:
        # TP/SL 走独立 reduce-only 触发单（非 attached 分支）
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

    # ---- 只读 ----

    async def fetch_equity(self) -> float:
        await self._ensure_markets()
        bal = await asyncio.to_thread(self._ex.fetch_balance)
        usdt = bal.get("USDT") or {}
        return float(usdt.get("total") or 0)

    async def fetch_market(self, symbol: str) -> dict:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        if s not in self._ex.markets:
            raise ValueError(f"Bitget 无此交易对（或已下架）：{s}")
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
        await asyncio.to_thread(
            self._ex.set_leverage, leverage, s, {"productType": "USDT-FUTURES"}
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
        """挂独立 SL：市价触发单（plan order）reduce-only，数量=当前持仓。"""
        if sl is None:
            return
        await self._ensure_markets()
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("挂 SL 时无持仓：%s", symbol)
            return
        close_side = "sell" if pos["side"] == "long" else "buy"
        await asyncio.to_thread(
            self._ex.create_order, self.to_ccxt_symbol(symbol),
            "market", close_side, pos["qty"], None,
            {"triggerPrice": sl, "reduceOnly": True, "productType": "USDT-FUTURES"},
        )
        log.info("已挂独立 SL：%s @%s（qty=%s）", symbol, sl, pos["qty"])

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """移动止损 = 撤旧 SL 触发单 + 按新价重挂（Bitget 无改 SL 端点）。"""
        sl_price = kwargs.get("sl_price")
        if sl_price is None:
            raise ValueError("amend_order 需要 sl_price")
        await self._ensure_markets()
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("移动止损时无持仓：%s", symbol)
            return
        open_orders = await self.fetch_open_orders(symbol)
        for o in open_orders:
            if o.get("reduce_only") and o.get("type") == "market" and o.get("stop_price"):
                await self.cancel_order(o["id"], symbol)
        close_side = "sell" if pos["side"] == "long" else "buy"
        await asyncio.to_thread(
            self._ex.create_order, self.to_ccxt_symbol(symbol),
            "market", close_side, pos["qty"], None,
            {"triggerPrice": sl_price, "reduceOnly": True, "productType": "USDT-FUTURES"},
        )
        log.info("已移动止损：%s SL=%s", symbol, sl_price)

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._ensure_markets()
        await asyncio.to_thread(
            self._ex.cancel_order, order_id, self.to_ccxt_symbol(symbol),
            {"productType": "USDT-FUTURES"},
        )

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        await self._ensure_markets()
        await asyncio.to_thread(
            self._ex.cancel_all_orders, self.to_ccxt_symbol(symbol),
            {"productType": "USDT-FUTURES"},
        )

    async def fetch_position(self, symbol: str) -> dict | None:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol)
        positions = await asyncio.to_thread(
            self._ex.fetch_positions, [s], {"productType": "USDT-FUTURES"}
        )
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
        positions = await asyncio.to_thread(
            self._ex.fetch_positions, None, {"productType": "USDT-FUTURES"}
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
                "sl_price": None,
            })
        return out

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(symbol) if symbol else None
        params = {"productType": "USDT-FUTURES"}
        orders = await asyncio.to_thread(self._ex.fetch_open_orders, s, None, None, params)
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
