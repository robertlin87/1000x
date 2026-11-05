"""架構 B 信號源（預留）：服務端中轉。

你方官方 Bot 以管理員身份入群接收全部消息，服務端對每個訂閱者調用
getChatMember 校驗成員狀態，僅向仍在群者經私有 API 推送信號；客戶端本機下單。
與架構 A 實現同一 SignalSource 接口，執行引擎零改動。
"""
from __future__ import annotations

from .base import SignalSource


class BotApiSource(SignalSource):
    """TODO 商業化階段：訂閱你方推送 API，解析後走同一 pipeline。"""

    async def start(self) -> None:
        raise NotImplementedError("架構 B：待商業化階段實現")

    async def stop(self) -> None:
        raise NotImplementedError("架構 B：待商業化階段實現")
