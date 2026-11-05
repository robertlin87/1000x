"""執行回執通知：下單/改單/平倉/告警回推設定的 TG 會話。"""
from __future__ import annotations

import logging

log = logging.getLogger("autotrade.notify")


class Notifier:
    """dry_run 時僅打日誌；正式運行時經 Telethon 發到 config.notify.send_to。

    client 參數留到 M2 裝配（傳入與信號源共用的 TelegramClient）。
    """

    def __init__(self, dry_run: bool = True, send_to: str = "", client=None) -> None:
        self._dry_run = dry_run
        self._send_to = send_to
        self._client = client

    async def send(self, text: str) -> None:
        if self._dry_run:
            log.info("[dry-run] %s", text)
            return
        if self._client is not None and self._send_to:
            await self._client.send_message(self._send_to, text)
        else:
            log.info("[no-target] %s", text)
