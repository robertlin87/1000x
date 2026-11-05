"""Bybit 適配器（MVP）：ccxt.bybit 封裝，USDT 永續（線性合約）+ 統一帳戶（UTA）。

真實驗證過的要點（2026-11-02）：
- ccxt unified symbol 格式為 `BASE/USDT:USDT`（不是 BASEUSDT）
- 餘額/權益在 UNIFIED 帳戶的 totalEquity 欄位；coin 列表可能為空（未儲值/無幣）
- 合約倍數 contractSize 對多數山寨幣為 1.0
- set_leverage / 下單 / 查持倉掛單需帶 accountType=UNIFIED（ccxt 大部分自動處理）
- 隨單附 SL/TP：單檔用 create_order 的 stopLossPrice/takeProfitPrice；多檔 TP 用
  reduce-only 限價單（由 OrderManager 編排，本適配器只提供原子操作）
"""
from __future__ import annotations

import asyncio
import logging

import ccxt

from ..proxy import resolve_proxy
from .base import ExchangeAdapter, NewOrder

log = logging.getLogger("autotrade.exchange.bybit")


# 現貨 symbol 名 → Bybit USDT 永續 symbol 名（個別幣兩者不同名）。
# 例：PUMP 現貨 / PUMPFUN 永續；同名幣（如 MNT、LIT）無需映射。
# 遇到報單幣在 Bybit 永續找不到時，先查這裡是否需要加映射。
_SYMBOL_ALIASES = {
    "PUMP": "PUMPFUN",
}
_SYMBOL_ALIASES_REVERSE = {v: k for k, v in _SYMBOL_ALIASES.items()}


class BybitAdapter(ExchangeAdapter):
    def __init__(self, api_key: str, secret: str, testnet: bool = False,
                 proxy: dict | None = None) -> None:
        if not api_key or not secret:
            raise ValueError("Bybit apiKey/secret 未設定")
        ccxt_cfg: dict = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # USDT 永續（線性合約）
                # Bybit 預設 recvWindow=5000ms；本機時鐘慢 5~6 秒時所有私有
                # 請求會被 10002 拒單。放寬到 20s 兜底，治本見 _ensure_markets
                "recvWindow": 20000,
            },
        }
        # 自動適配本機網絡連線（或 config 顯式指定）
        resolved = resolve_proxy(proxy, default_type="http")
        if resolved:
            ptype, addr, port = resolved
            url = f"{ptype}://{addr}:{port}"
            ccxt_cfg["proxies"] = {"http": url, "https": url}
        self._ex = ccxt.bybit(ccxt_cfg)
        if testnet:
            self._ex.set_sandbox_mode(True)
        self._markets_loaded = False
        self._time_synced = False

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": True}

    # ---- 工具 ----

    async def _ensure_markets(self) -> None:
        # 所有私有（簽名）請求都先經過這裡：按交易所服務器時間校準一次。
        # ccxt.bybit.nonce() = milliseconds() - options['timeDifference']，
        # load_time_difference() 寫入差值後簽名時間戳自動與服務器對齊。
        # fetch_time 是公開端點、不受時鐘偏差影響，校準請求本身一定能發出去。
        if not self._time_synced:
            self._time_synced = True
            try:
                diff = await asyncio.to_thread(self._ex.load_time_difference)
                log.info("Bybit 時鐘校準：本機相對服務器偏差 %s ms，已自動補償", diff)
            except Exception as e:  # noqa: BLE001
                log.warning("Bybit 時鐘校準失敗（改用本機時間，靠 recvWindow 兜底）：%s", e)
        if not self._markets_loaded:
            await asyncio.to_thread(self._ex.load_markets)
            self._markets_loaded = True

    @staticmethod
    def to_ccxt_symbol(symbol: str) -> str:
        """內部 symbol（如 LITUSDT）→ ccxt unified（LIT/USDT:USDT）。

        個別幣在 Bybit 的現貨名與永續名不同（如 PUMP 現貨 / PUMPFUN 永續），
        經 _SYMBOL_ALIASES 映射到正確的永續名。
        """
        if "/" in symbol:
            return symbol
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        base = _SYMBOL_ALIASES.get(base, base)
        return f"{base}/USDT:USDT"

    @staticmethod
    def from_ccxt_symbol(symbol: str) -> str:
        """ccxt unified（INJ/USDT:USDT）→ 內部 symbol（INJUSDT），含別名反向映射。"""
        if "/" not in symbol:
            return symbol
        base, _, settle = symbol.partition("/")
        quote = settle.split(":")[0]
        base = _SYMBOL_ALIASES_REVERSE.get(base, base)
        return f"{base}{quote}"

    # ---- 只讀 ----

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
            raise ValueError(f"Bybit 無此交易對（或已下架）：{s}")
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
            # Bybit 110043「leverage not modified」= 槓桿已是目標值，冪等成功
            msg = str(e)
            if "leverage not modified" in msg or "110043" in msg:
                log.info("槓桿已是 %sx（冪等跳過）：%s", leverage, symbol)
                return
            raise

    async def create_order(self, o: NewOrder) -> str:
        await self._ensure_markets()
        s = self.to_ccxt_symbol(o.symbol)
        params: dict = {}
        if o.reduce_only:
            params["reduceOnly"] = True
        if o.sl_price is not None:
            # 用 attached stopLoss（tpslMode），Bybit 按持倉方向自動判 triggerDirection；
            # 若用 stopLossPrice 會走 trigger-order 分支，方向判斷錯誤（110092）
            params["stopLoss"] = o.sl_price
        # 單檔 TP 隨單附；多檔 TP 由 OrderManager 用 reduce-only 限價單實現
        if not o.reduce_only and len(o.tp_prices) == 1:
            params["takeProfit"] = o.tp_prices[0]
        res = await asyncio.to_thread(
            self._ex.create_order, s, o.order_type, o.side, o.qty, o.price, params
        )
        return str(res.get("id") or res.get("orderId") or "")

    async def attach_sl_tp(self, order_id: str, symbol: str, sl, tps) -> None:
        # Bybit 支持隨單附 SL/TP（supports_attached_sl=True），開倉已帶 SL；
        # 多檔 TP 由 OrderManager 用 reduce-only 限價單實現，不經過這裡。
        return None

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        """移動止損：改持倉 SL。

        ccxt 的 bybit 沒有 set_stop_loss；改持倉止損走 /v5/position/trading-stop
        端點（create_order + tradingStopEndpoint=True + stopLossPrice），
        該端點按持倉方向自動判斷觸發方向，無需 triggerDirection。
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
        """全部持倉（內部 symbol 格式），風控與看護對賬的數據源。"""
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
