"""管线单测：双通道（编辑行 + 新消息通知）同一操作只触发一次（M1 验收）。"""
import unittest
from pathlib import Path

from autotrade.main import MessagePipeline
from autotrade.notify.notifier import Notifier
from autotrade.signal_source.base import RawMessage
from autotrade.storage.db import add_signal_op, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "messages"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__(dry_run=False)
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


def raw(text: str, msg_id: int, is_edit: bool) -> RawMessage:
    return RawMessage(chat_id=12345, chat_title="信号群", sender_id=1,
                      msg_id=msg_id, text=text, ts="", is_edit=is_edit)


class TestPipelineDedup(unittest.IsolatedAsyncioTestCase):
    async def test_dual_channel_close_fires_once(self):
        db = await init_db(":memory:")
        notifier = RecordingNotifier()
        p = MessagePipeline(db, notifier)
        edit_text = load("order_187_syn_short.txt")
        notice_text = load("notice_187_close.txt")

        # 1) 编辑通道：报单 + 操作行（含 🟥 已平倉）
        await p.handle(raw(edit_text, 100, is_edit=True))
        # 2) 新消息通道：紧凑通知同操作
        await p.handle(raw(notice_text, 101, is_edit=False))
        # 3) 再次编辑同内容（重复推送）
        await p.handle(raw(edit_text, 100, is_edit=True))

        closes = [s for s in notifier.sent if "close" in s]
        self.assertEqual(len(closes), 1, f"close 应只触发一次：{notifier.sent}")
        await db.close()

    async def test_edit_then_notice_order_independent(self):
        # 反向顺序：先通知后编辑，同样只触发一次
        db = await init_db(":memory:")
        notifier = RecordingNotifier()
        p = MessagePipeline(db, notifier)
        await p.handle(raw(load("notice_188_close.txt"), 1, is_edit=False))
        await p.handle(raw(load("order_188_giggle_long.txt"), 2, is_edit=True))
        closes = [s for s in notifier.sent if "close" in s]
        self.assertEqual(len(closes), 1, f"close 应只触发一次：{notifier.sent}")
        await db.close()

    async def test_new_entry_signal_recorded(self):
        db = await init_db(":memory:")
        notifier = RecordingNotifier()
        p = MessagePipeline(db, notifier)
        await p.handle(raw(load("order_216_lit_long.txt"), 3, is_edit=False))
        self.assertTrue(any("新报单" in s for s in notifier.sent))
        # 同一报单重复推送 → 不重复通知
        await p.handle(raw(load("order_216_lit_long.txt"), 4, is_edit=False))
        self.assertEqual(sum("新报单" in s for s in notifier.sent), 1)
        await db.close()

    async def test_add_signal_op_duplicate_ignored(self):
        db = await init_db(":memory:")
        self.assertTrue(await add_signal_op(db, 1, "187", "h1", "line", "edit", "close"))
        self.assertFalse(await add_signal_op(db, 1, "187", "h1", "line2", "notice", "close"))
        # 同 hash 不同 order_id 是不同事件
        self.assertTrue(await add_signal_op(db, 1, "188", "h1", "line", "edit", "close"))
        await db.close()


if __name__ == "__main__":
    unittest.main()
