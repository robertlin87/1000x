"""Bitunix 适配器（手写 REST 兜底）：ccxt 4.5.91 不支持 bitunix。

签名与端点按官方 demo（github.com/BitunixOfficial/open-api）实现：
- Base: https://fapi.bitunix.com
- 请求头 api-key / timestamp(ms) / nonce / sign
- sign = HMAC-SHA256(secret, timestamp + nonce + method + path + body) hex
- side: 1=buy 2=sell；positionSide: 1=long 2=short；orderType: 1=limit 2=market
- 带 stopPrice 的市价单 = 条件触发单（SL 用）

字段名与返回结构按官方 demo 编写，**需真实小单实测确认**（用户逐家验证时
如有出入，按实测响应调整 _parse_* 即可，接口骨架不变）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import time

import requests

from ..proxy import resolve_proxy
from .base import ExchangeAdapter, NewOrder

log = logging.getLogger("autotrade.exchange.bitunix")

BASE_URL = "https://fapi.bitunix.com"


class BitunixRestAdapter(ExchangeAdapter):
    def __init__(self, api_key: str, secret: str, proxy: dict | None = None) -> None:
        if not api_key or not secret:
            raise ValueError("Bitunix apiKey/secret 未配置")
        self._api_key = api_key
        self._secret = secret
        resolved = resolve_proxy(proxy, default_type="http")
        self._proxies = None
        if resolved:
            ptype, addr, port = resolved
            url = f"{ptype}://{addr}:{port}"
            self._proxies = {"http": url, "https": url}
        self._markets: dict[str, dict] = {}

    @property
    def capabilities(self) -> dict:
        # TP/SL 走独立 reduce-only 触发单（非 attached 分支）
        return {"supports_attached_sl": False}

    # ---- 底层请求 ----

    def _sign(self, method: str, path: str, body: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        nonce = "".join(random.choices("0123456789", k=10))
        sign = hmac.new(
            self._secret.encode(),
            f"{timestamp}{nonce}{method}{path}{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": self._api_key,
            "timestamp": timestamp,
            "nonce": nonce,
            "sign": sign,
        }

    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        """同步 HTTP 请求，返回解析后的 JSON（外层 code=0 为成功）。"""
        if params is None:
            params = {}
        body = ""
        url = BASE_URL + path
        if method == "GET":
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                path = f"{path}?{query}"
                url = f"{url}?{query}"
        else:
            body = _json_dumps(params)
        headers = self._sign(method, path, body)
        headers["Content-Type"] = "application/json"
        resp = requests.post if method == "POST" else requests.get
        r = resp(url, headers=headers, data=body, timeout=15, proxies=self._proxies)
        r.raise_for_status()
        data = r.json()
        if data.get("code") not in (0, "0", None):
            raise RuntimeError(f"Bitunix API 错误 code={data.get('code')} msg={data.get('msg')}")
        return data.get("data") or {}

    # ---- 只读 ----

    async def fetch_equity(self) -> float:
        data = await asyncio.to_thread(self._request, "GET", "/api/v1/futures/account")
        # 防御性解析：不同字段名都尝试（实测后收敛到真实字段）
        for key in ("totalEquity", "equity", "totalWalletBalance", "availableBalance"):
            if isinstance(data, dict) and data.get(key) is not None:
                return float(data[key])
        usdt = data.get("usdt") or {}
        return float(usdt.get("equity") or usdt.get("balance") or 0)

    async def _load_market(self, symbol: str) -> dict:
        s = self.to_ccxt_symbol(symbol)
        if s in self._markets:
            return self._markets[s]
        data = await asyncio.to_thread(
            self._request, "GET", "/api/v1/futures/market/contracts"
        )
        for c in data if isinstance(data, list) else []:
            sym = str(c.get("symbol") or "")
            if not sym:
                continue
            self._markets[sym] = c
        if s not in self._markets:
            raise ValueError(f"Bitunix 无此交易对（或已下架）：{s}")
        return self._markets[s]

    @staticmethod
    def to_ccxt_symbol(symbol: str) -> str:
        """Bitunix 合约 symbol 即 BASEUSDT（如 BTCUSDT），内部格式一致。"""
        return symbol

    @staticmethod
    def from_ccxt_symbol(symbol: str) -> str:
        return symbol

    async def fetch_market(self, symbol: str) -> dict:
        c = await self._load_market(symbol)
        price_prec = int(c.get("pricePrecision") or 4)
        qty_prec = int(c.get("qtyPrecision") or 0)
        return {
            "symbol": self.to_ccxt_symbol(symbol),
            "contractSize": float(c.get("faceValue") or 1.0),  # 每张合约的币数
            "precision": {
                "amount": 10 ** -qty_prec,
                "price": 10 ** -price_prec,
            },
            "limits": {"amount": {"min": 10 ** -qty_prec}},
            "active": True,
        }

    async def fetch_ticker(self, symbol: str) -> float:
        s = self.to_ccxt_symbol(symbol)
        data = await asyncio.to_thread(
            self._request, "GET", "/api/v1/futures/market/ticker", {"symbol": s}
        )
        return float(data.get("last") or data.get("lastPrice") or 0)

    # ---- 交易 ----

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await asyncio.to_thread(
            self._request, "POST", "/api/v1/futures/set-leverage",
            {"symbol": self.to_ccxt_symbol(symbol), "leverage": leverage},
        )

    async def create_order(self, o: NewOrder) -> str:
        s = self.to_ccxt_symbol(o.symbol)
        params = {
            "symbol": s,
            "side": 1 if o.side == "buy" else 2,
            "orderType": 1 if o.order_type == "limit" else 2,
            "quantity": o.qty,
        }
        if o.order_type == "limit" and o.price is not None:
            params["price"] = o.price
        if o.reduce_only:
            params["reduceOnly"] = True
        data = await asyncio.to_thread(
            self._request, "POST", "/api/v1/futures/order", params
        )
        return str(data.get("orderId") or "")

    async def attach_sl_tp(self, order_id: str, symbol: str, sl, tps) -> None:
        """挂独立 SL：市价条件触发单 reduce-only（数量=当前持仓）。"""
        if sl is None:
            return
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("挂 SL 时无持仓：%s", symbol)
            return
        params = {
            "symbol": self.to_ccxt_symbol(symbol),
            "side": 2 if pos["side"] == "long" else 1,  # 平仓方向
            "orderType": 2,
            "quantity": pos["qty"],
            "stopPrice": sl,
            "reduceOnly": True,
        }
        await asyncio.to_thread(
            self._request, "POST", "/api/v1/futures/order", params
        )
        log.info("已挂独立 SL：%s @%s（qty=%s）", symbol, sl, pos["qty"])

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """移动止损 = 撤旧 SL 触发单 + 按新价重挂。"""
        sl_price = kwargs.get("sl_price")
        if sl_price is None:
            raise ValueError("amend_order 需要 sl_price")
        pos = await self.fetch_position(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            log.warning("移动止损时无持仓：%s", symbol)
            return
        for o in await self.fetch_open_orders(symbol):
            if o.get("reduce_only") and o.get("type") == "market" and o.get("stop_price"):
                await self.cancel_order(o["id"], symbol)
        params = {
            "symbol": self.to_ccxt_symbol(symbol),
            "side": 2 if pos["side"] == "long" else 1,
            "orderType": 2,
            "quantity": pos["qty"],
            "stopPrice": sl_price,
            "reduceOnly": True,
        }
        await asyncio.to_thread(
            self._request, "POST", "/api/v1/futures/order", params
        )
        log.info("已移动止损：%s SL=%s", symbol, sl_price)

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        import urllib.parse

        await asyncio.to_thread(
            self._request, "DELETE",
            f"/api/v1/futures/order?{urllib.parse.urlencode({'orderId': order_id})}"
        )

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        import urllib.parse

        await asyncio.to_thread(
            self._request, "DELETE",
            f"/api/v1/futures/all-order?{urllib.parse.urlencode({'symbol': self.to_ccxt_symbol(symbol)})}"
        )

    async def fetch_position(self, symbol: str) -> dict | None:
        s = self.to_ccxt_symbol(symbol)
        data = await asyncio.to_thread(self._request, "GET", "/api/v1/futures/positions")
        for p in data if isinstance(data, list) else []:
            if str(p.get("symbol") or "") != s:
                continue
            qty = float(p.get("qty") or p.get("quantity") or 0)
            if qty == 0:
                continue
            side_raw = p.get("positionSide")
            side = "long" if str(side_raw) in ("1", "LONG", "long") else "short"
            return {
                "symbol": s,
                "side": side,
                "qty": qty,
                "entry_price": float(p.get("entryPrice") or 0),
                "sl_price": None,
            }
        return None

    async def fetch_all_positions(self) -> list[dict]:
        data = await asyncio.to_thread(self._request, "GET", "/api/v1/futures/positions")
        out: list[dict] = []
        for p in data if isinstance(data, list) else []:
            qty = float(p.get("qty") or p.get("quantity") or 0)
            if qty == 0:
                continue
            side_raw = p.get("positionSide")
            out.append({
                "symbol": str(p.get("symbol") or ""),
                "side": "long" if str(side_raw) in ("1", "LONG", "long") else "short",
                "qty": qty,
                "entry_price": float(p.get("entryPrice") or 0),
                "sl_price": None,
            })
        return out

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        params = {}
        if symbol:
            params["symbol"] = self.to_ccxt_symbol(symbol)
        data = await asyncio.to_thread(
            self._request, "GET", "/api/v1/futures/orders", params
        )
        out = []
        for o in data if isinstance(data, list) else []:
            otype_raw = o.get("orderType")
            out.append({
                "id": str(o.get("orderId") or ""),
                "symbol": str(o.get("symbol") or ""),
                "side": "buy" if str(o.get("side")) == "1" else "sell",
                "type": "limit" if str(otype_raw) == "1" else "market",
                "qty": float(o.get("quantity") or 0),
                "price": o.get("price"),
                "stop_price": o.get("stopPrice"),
                "reduce_only": bool(o.get("reduceOnly")),
            })
        return out


def _json_dumps(params: dict) -> str:
    import json
    return json.dumps(params, separators=(",", ":"))
