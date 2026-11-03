"""信号源基类与消息类型。

架构 A（Telethon userbot，群资格即授权）与架构 B（官方 Bot + getChatMember
校验 + API 推送）实现同一接口，执行引擎对信号来源零感知。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(slots=True)
class RawMessage:
    """一条原始消息（新消息或编辑后的全文）。"""
    chat_id: int
    chat_title: str
    sender_id: int | None
    msg_id: int
    text: str
    ts: str
    is_edit: bool = False


MessageHandler = Callable[[RawMessage], Awaitable[None]]


class SignalSource:
    """所有信号源的基类。start() 后由实现方持续调用 handler。"""

    def __init__(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
