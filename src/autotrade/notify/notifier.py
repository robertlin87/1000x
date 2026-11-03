"""执行回执通知：下单/改单/平仓/告警回推配置的 TG 会话。"""
from __future__ import annotations

import logging

log = logging.getLogger("autotrade.notify")


class Notifier:
    """dry_run 时仅打日志；正式运行时经 Telethon 发到 config.notify.send_to。

    client 参数留到 M2 装配（传入与信号源共用的 TelegramClient）。
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
