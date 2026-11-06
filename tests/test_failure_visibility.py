"""所有沒辦成的動作都要在視窗（ERROR 日誌）與 temp 失敗記錄裡報出來。

使用者規則（2026-11-06）：「所有操作失敗的，都必須在窗口上報出來」。
這一組檢查專門盯「靜默跳過」：條件不滿足時只寫一行普通日誌就返回的路徑。
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from autotrade.execution.order_manager import OrderManager
from autotrade.execution.trigger_router import TriggerRouter
from autotrade.main import MessagePipeline
from autotrade.signal_source.base import RawMessage
from autotrade.storage.db import init_db
from tests.test_execution import RecordingNotifier, StubAdapter
from tests.test_pipeline import raw

EXCHANGE_REASON = "Bybit retCode 10002: 餘額不足"


class TestFailureVisibility(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = patch("autotrade.logfile.paths.temp_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncSetUp(self):
        self.db = await init_db(":memory:")
        self.addAsyncCleanup(self.db.close)

    def _failed_log(self) -> str:
        path = self.tmp / "failed_actions.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _router(self, adapter):
        notifier = RecordingNotifier()
        return TriggerRouter(adapter, OrderManager(adapter), notifier), notifier

    def _no_wait(self):
        return patch("asyncio.sleep", new_callable=AsyncMock)

    async def test_modify_without_archive_is_reported(self):
        """改單查不到舊報單：整條沒執行，必須在視窗報出來。"""
        router, _ = self._router(StubAdapter())
        with self.assertLogs(level="ERROR") as logs:
            await router.on_event("339", "STARUSDT", "modify",
                                  mod_fields={"tps": [(3, 0.042)]}, old_signal=None)
        text = "\n".join(logs.output)
        self.assertIn("339", text)
        self.assertIn("未執行", text)
        self.assertIn("339", self._failed_log())

    async def test_missing_symbol_is_reported(self):
        router, _ = self._router(StubAdapter())
        with self.assertLogs(level="ERROR") as logs:
            await router.on_event("339", None, "close")
        text = "\n".join(logs.output)
        self.assertIn("339", text)
        self.assertIn("未執行", text)
        self.assertIn("339", self._failed_log())

    async def test_move_sl_without_price_is_reported(self):
        router, _ = self._router(StubAdapter())
        with self.assertLogs(level="ERROR") as logs:
            await router.on_event("339", "STARUSDT", "move_sl", None, None)
        text = "\n".join(logs.output)
        self.assertIn("339", text)
        self.assertIn("未執行", text)

    async def test_amend_sl_without_position_is_reported(self):
        """移損查無持倉：不能當成功，要報出具體原因。"""
        router, _ = self._router(StubAdapter(position=None))
        with self._no_wait(), self.assertLogs(level="ERROR") as logs:
            await router.on_event("339", "STARUSDT", "hedge", None, 0.037)
        text = "\n".join(logs.output)
        self.assertIn("持倉", text)
        self.assertIn("請手動操作", text)
        self.assertIn("持倉", self._failed_log())

    async def test_partial_tp_failure_is_reported(self):
        """改單有一檔舊掛單找不到：不能只打「執行成功」。"""
        adapter = StubAdapter(
            position={"symbol": "STARUSDT", "side": "long", "qty": 4.0},
            open_orders=[], ticker=0.03,
        )
        router, _ = self._router(adapter)
        with self._no_wait(), self.assertLogs(level="ERROR") as logs:
            await router.on_event(
                "339", "STARUSDT", "modify",
                mod_fields={"tps": [(3, 0.042)], "sl": None, "entry": None},
                old_signal=__import__("types").SimpleNamespace(
                    side="long", sl=0.03556, tps=[0.03776, 0.039226, 0.041059, 0.045825]
                ),
            )
        text = "\n".join(logs.output)
        self.assertIn("TP3", text)
        self.assertIn("請手動", text)

    async def test_pipeline_exception_is_reported_with_reason(self):
        """最外層兜底：未預期的錯誤也要把交易所回的原因打到視窗。"""
        pipeline = MessagePipeline(self.db, RecordingNotifier())
        with patch.object(pipeline, "_handle_new", new_callable=AsyncMock,
                          side_effect=RuntimeError(EXCHANGE_REASON)):
            with self.assertLogs(level="ERROR") as logs:
                await pipeline.handle(RawMessage(chat_id=1, chat_title="信號群",
                                                 sender_id=1, msg_id=1,
                                                 text="anything", ts="", is_edit=False))
        text = "\n".join(logs.output)
        self.assertIn(EXCHANGE_REASON, text)
        self.assertIn(EXCHANGE_REASON, self._failed_log())


if __name__ == "__main__":
    unittest.main()
