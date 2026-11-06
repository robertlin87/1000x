"""重啟後收到「套保」新消息：不看任何本地舊記錄，直接定位該幣的持倉放保本。

場景（使用者 2026-11-06）：
1. 之前報過單、也建了倉
2. 程式重啟／重裝／換資料庫，本地沒有這張報單的記錄
3. 群裡來一條新消息：📌訂單 221 SOLUSDT 做多 🔒 套保（SL → 進場價 93.81）
4. 程式按這條新消息，對 SOLUSDT 的持倉把止損改到 93.81
5. 定位靠「一個幣一個頭寸」直接查交易所持倉，不靠本地舊記錄
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autotrade.execution.order_manager import OrderManager
from autotrade.execution.trigger_router import TriggerRouter
from autotrade.main import MessagePipeline
from autotrade.parser.notice_parser import NoticeParser
from autotrade.signal_source.base import RawMessage
from autotrade.storage.db import init_db
from tests.test_execution import RecordingNotifier, StubAdapter

TEXT = "📌訂單 221 SOLUSDT 做多 🔒 套保（SL → 進場價 93.81）"


class TestHedgeAfterRestart(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch("autotrade.logfile.paths.temp_dir", return_value=Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_notice_parses_order_symbol_and_price(self):
        ev = NoticeParser().parse(TEXT)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.order_id, "221")
        self.assertEqual(ev.symbol, "SOLUSDT")
        self.assertEqual(ev.action_type, "hedge")
        self.assertEqual(ev.price, 93.81)

    async def test_new_hedge_notice_targets_position_without_local_signal(self):
        """資料庫是空的（重啟後），仍能對正確的持倉放保本。"""
        db = await init_db(":memory:")
        self.addAsyncCleanup(db.close)
        notifier = RecordingNotifier()
        adapter = StubAdapter(
            position={"symbol": "SOLUSDT", "side": "long", "qty": 12.0},
        )
        router = TriggerRouter(adapter, OrderManager(adapter), notifier)
        pipeline = MessagePipeline(db, notifier, router)

        raw = RawMessage(chat_id=12345, chat_title="信號群", sender_id=1,
                         msg_id=99, text=TEXT, ts="", is_edit=False)
        await pipeline.handle(raw)

        self.assertEqual(adapter.amended, [("SOLUSDT", 93.81)])
        self.assertTrue(any("移動止損" in s for s in notifier.sent), notifier.sent)

    async def test_same_notice_twice_only_executes_once(self):
        """雙通道／重複推送：同一條套保指令不重複改單。"""
        db = await init_db(":memory:")
        self.addAsyncCleanup(db.close)
        adapter = StubAdapter(
            position={"symbol": "SOLUSDT", "side": "long", "qty": 12.0},
        )
        router = TriggerRouter(adapter, OrderManager(adapter), RecordingNotifier())
        pipeline = MessagePipeline(db, RecordingNotifier(), router)
        for msg_id in (99, 100):
            await pipeline.handle(RawMessage(
                chat_id=12345, chat_title="信號群", sender_id=1,
                msg_id=msg_id, text=TEXT, ts="", is_edit=False,
            ))
        self.assertEqual(adapter.amended, [("SOLUSDT", 93.81)])


if __name__ == "__main__":
    unittest.main()
