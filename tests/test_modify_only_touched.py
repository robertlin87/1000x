"""改單：只動分析師明確寫出來的價格，其他一個字都不改。

使用者規則（2026-11-06）：分析師原本掛 4 檔 TP，過一陣子只改 TP3、TP4，
那程式就只改這兩檔；SL、進場價、TP1、TP2 動都不要動。
"""
import unittest

from autotrade.execution.order_manager import OrderManager
from autotrade.main import MessagePipeline
from autotrade.parser.entry_parser import Signal
from autotrade.storage.db import get_signal, init_db, upsert_signal
from tests.test_execution import StubAdapter
from tests.test_pipeline import RecordingNotifier, raw

OLD_TPS = [0.03776, 0.039226, 0.041059, 0.045825]
OLD_SL = 0.03556
OLD_ENTRY = 0.03666


def _old_signal():
    return Signal(
        order_id="339", symbol="STARUSDT", side="long", entry=OLD_ENTRY,
        is_limit=False, leverage=10, sl=OLD_SL, tps=list(OLD_TPS),
    )


class TestModifyOnlyTouchedPrices(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await init_db(":memory:")
        self.addAsyncCleanup(self.db.close)
        await upsert_signal(self.db, 12345, _old_signal())
        self.pipeline = MessagePipeline(self.db, RecordingNotifier())

    async def test_only_tp3_tp4_changed(self):
        """只改 TP3、TP4：TP1/TP2/SL/進場價全部保持原值。"""
        notice = ("📌訂單 339 STARUSDT 做多 ✏️ 訂單修改 (2026-11-06 10:00:00) · "
                  "TP3 0.042 · TP4 0.046")
        await self.pipeline.handle(raw(notice, 2, is_edit=False))
        got = await get_signal(self.db, 12345, "339")
        self.assertEqual(got.tps, [OLD_TPS[0], OLD_TPS[1], 0.042, 0.046])
        self.assertEqual(got.sl, OLD_SL)
        self.assertEqual(got.entry, OLD_ENTRY)

    async def test_only_sl_changed_keeps_all_tps(self):
        """只改止損：四檔 TP 與進場價保持原值。"""
        notice = ("📌訂單 339 STARUSDT 做多 ✏️ 訂單修改 (2026-11-06 10:01:00) · "
                  "止損 0.03500")
        await self.pipeline.handle(raw(notice, 3, is_edit=False))
        got = await get_signal(self.db, 12345, "339")
        self.assertEqual(got.tps, OLD_TPS)
        self.assertEqual(got.sl, 0.03500)
        self.assertEqual(got.entry, OLD_ENTRY)

    async def test_all_four_tiers_still_four(self):
        """四檔都寫出來時，仍然是四檔、按檔位對號入座。"""
        notice = ("📌訂單 339 STARUSDT 做多 ✏️ 訂單修改 (2026-11-06 10:02:00) · "
                  "TP1 0.0380 · TP2 0.0395 · TP3 0.0420 · TP4 0.0460")
        await self.pipeline.handle(raw(notice, 4, is_edit=False))
        got = await get_signal(self.db, 12345, "339")
        self.assertEqual(got.tps, [0.0380, 0.0395, 0.0420, 0.0460])
        self.assertEqual(got.sl, OLD_SL)
        self.assertEqual(got.entry, OLD_ENTRY)

    async def test_no_archive_does_not_write_zero(self):
        """找不到原報單存檔時：不猜、不補 0，舊值一個字都不改。"""
        await self.pipeline._apply_modify_db(
            12345, "339", None,
            {"tps": [(3, 0.042), (4, 0.046)], "sl": None, "entry": None},
        )
        got = await get_signal(self.db, 12345, "339")
        self.assertEqual(got.tps, OLD_TPS)
        self.assertEqual(got.sl, OLD_SL)
        self.assertEqual(got.entry, OLD_ENTRY)

    async def test_exchange_side_only_replaces_tp3_tp4(self):
        """交易所端：只撤 TP3/TP4 兩張舊單、只重掛這兩張，TP1/TP2/SL 全不碰。"""
        adapter = StubAdapter(
            position={"symbol": "STARUSDT", "side": "long", "qty": 4.0},
            open_orders=[
                {"id": "tp1", "type": "limit", "reduce_only": True, "price": OLD_TPS[0], "qty": 1.0},
                {"id": "tp2", "type": "limit", "reduce_only": True, "price": OLD_TPS[1], "qty": 1.0},
                {"id": "tp3", "type": "limit", "reduce_only": True, "price": OLD_TPS[2], "qty": 1.0},
                {"id": "tp4", "type": "limit", "reduce_only": True, "price": OLD_TPS[3], "qty": 1.0},
            ],
            ticker=OLD_ENTRY,
        )
        await OrderManager(adapter).apply_modify(
            "STARUSDT", "long",
            {"tps": [(3, 0.042), (4, 0.046)], "sl": None, "entry": None},
            list(OLD_TPS), OLD_SL,
        )
        self.assertEqual(adapter.cancelled_ids, ["tp3", "tp4"])
        self.assertEqual(adapter.amended, [])
        reorders = [c for c in adapter.created if c["reduce_only"]]
        self.assertEqual([o["price"] for o in reorders], [0.042, 0.046])


if __name__ == "__main__":
    unittest.main()
