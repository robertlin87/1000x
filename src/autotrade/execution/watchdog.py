"""轮询看护：全平后残留挂单的兜底清理（无状态，交易所为唯一事实源）。

全平场景（SL 触发 / 末档 TP 成交 / 手工平仓）有 TG 通知（❌ 止損 /
✅ 全部止盈 / 🟥 已平倉），事件通道会撤残留挂单；本模块是兜底：
TG 断线、程序重启错过通知时，残留的 reduce-only 挂单仍会被清掉。

规则 2026-11-04：任何全平后残留挂单都要删；TP1-3 部分平仓的剩余档位保留。
判定（每 30s 全量查一次交易所）：
- 某 symbol 无持仓 + 有 reduce-only 挂单 → 全平后的残留 → 撤
- 某 symbol 无持仓 + 只有非 reduce-only 挂单 → 进场限价单还在等待，不撤
- 其余不动
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
        """后台循环：每隔 interval 秒对账一次。"""
        while True:
            await asyncio.sleep(self._interval)
            await self.tick()

    async def tick(self) -> None:
        """全量对账：持仓 + 挂单一次查清，找全平残留。"""
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
                        f"🧹 全平后残留挂单已清理 {sym}（{len(os_)} 个 reduce-only）"
                    )
                except Exception:
                    log.exception("残留挂单清理失败：%s", sym)
        except Exception:
            log.exception("看护对账失败")
