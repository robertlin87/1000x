"""輪詢看護：全平後殘留掛單的兜底清理（無狀態，交易所為唯一事實源）。

全平場景（SL 觸發 / 末檔 TP 成交 / 手工平倉）有 TG 通知（❌ 止損 /
✅ 全部止盈 / 🟥 已平倉），事件通道會撤殘留掛單；本模塊是兜底：
TG 斷線、程序重啟錯過通知時，殘留的 reduce-only 掛單仍會被清掉。

規則 2026-11-04：任何全平後殘留掛單都要刪；TP1-3 部分平倉的剩餘檔位保留。
判定（每 30s 全量查一次交易所）：
- 某 symbol 無持倉 + 有 reduce-only 掛單 → 全平後的殘留 → 撤
- 某 symbol 無持倉 + 只有非 reduce-only 掛單 → 進場限價單還在等待，不撤
- 其餘不動
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

log = logging.getLogger("autotrade.execution.watchdog")


class Watchdog:
    def __init__(self, adapter, notifier, interval: float = 30.0) -> None:
        self._adapter = adapter
        self._notifier = notifier
        self._interval = interval

    async def run(self) -> None:
        """背景循環：每隔 interval 秒對賬一次。"""
        while True:
            await asyncio.sleep(self._interval)
            await self.tick()

    async def tick(self) -> None:
        """全量對賬：持倉 + 掛單一次查清，找全平殘留。"""
        try:
            positions = await self._adapter.fetch_all_positions()
            held = {p["symbol"] for p in positions}
            orders = await self._adapter.fetch_open_orders()
            leftovers: dict[str, list[dict]] = defaultdict(list)
            for o in orders:
                if o.get("reduce_only") and o.get("symbol") not in held:
                    leftovers[o["symbol"]].append(o)
            for sym, os_ in leftovers.items():
                try:
                    await self._adapter.cancel_all_for_symbol(sym)
                    await self._notifier.send(
                        f"🧹 全平後殘留掛單已清理 {sym}（{len(os_)} 個 reduce-only）"
                    )
                except Exception:
                    log.exception("殘留掛單清理失敗：%s", sym)
        except Exception:
            log.exception("看護對賬失敗")
