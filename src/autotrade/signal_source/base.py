"""信號源基類與消息類型。

架構 A（Telethon userbot，群資格即授權）與架構 B（官方 Bot + getChatMember
校驗 + API 推送）實現同一接口，執行引擎對信號來源零感知。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(slots=True)
class RawMessage:
    """一條原始消息（新消息或編輯後的全文）。"""
    chat_id: int
    chat_title: str
    sender_id: int | None
    msg_id: int
    text: str
    ts: str
    is_edit: bool = False


MessageHandler = Callable[[RawMessage], Awaitable[None]]


class SignalSource:
    """所有信號源的基類。start() 後由實現方持續調用 handler。"""

    def __init__(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
