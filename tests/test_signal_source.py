"""TG 信号源生命周期单测：用完必须释放 session，避免 database is locked。

Telethon 的 SQLiteSession.process_entities() 写 entities 表不 commit，且
SQLiteSession 没有 __del__ —— 只有 client.disconnect()（内部调 session.close()）
才会 commit + 关闭连接。check_group_access/list_dialogs 若只 start() 不 disconnect，
向导里下一个 TelegramClient 打开同一个 .session 文件就会报 database is locked。
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from autotrade.signal_source.telegram_userbot import TelegramUserbotSource


async def _empty_dialogs():
    if False:  # pragma: no cover
        yield None


class TestSessionReleased(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        src = TelegramUserbotSource(
            handler=lambda raw: None,
            api_id=1,
            api_hash="deadbeef",
            session_name=str(Path(self._tmp.name) / "sess"),
            # enabled=true 走显式配置，单测不探测本机端口
            proxy={"enabled": True, "type": "socks5", "addr": "127.0.0.1", "port": 1},
        )
        self._real_client = src._client
        self.client = AsyncMock()
        self.client.get_entity = AsyncMock(
            return_value=MagicMock(title="信号群", username=None)
        )
        self.client.iter_dialogs = MagicMock(return_value=_empty_dialogs())
        src._client = self.client
        self.src = src

    async def asyncTearDown(self):
        self._real_client.session.close()
        self._tmp.cleanup()

    async def test_check_group_access_disconnects_on_success(self):
        ok, _ = await self.src.check_group_access()
        self.assertTrue(ok)
        self.client.disconnect.assert_awaited_once()

    async def test_check_group_access_disconnects_on_failure(self):
        self.client.get_entity.side_effect = RuntimeError("CHANNEL_PRIVATE")
        ok, _ = await self.src.check_group_access()
        self.assertFalse(ok)
        self.client.disconnect.assert_awaited_once()

    async def test_list_dialogs_disconnects(self):
        self.assertEqual(await self.src.list_dialogs(), [])
        self.client.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
