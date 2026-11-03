"""架构 B 信号源（预留）：服务端中转。

你方官方 Bot 以管理员身份入群接收全部消息，服务端对每个订阅者调用
getChatMember 校验成员状态，仅向仍在群者经私有 API 推送信号；客户端本机下单。
与架构 A 实现同一 SignalSource 接口，执行引擎零改动。
"""
from __future__ import annotations

from .base import SignalSource


class BotApiSource(SignalSource):
    """TODO 商业化阶段：订阅你方推送 API，解析后走同一 pipeline。"""

    async def start(self) -> None:
        raise NotImplementedError("架构 B：待商业化阶段实现")

    async def stop(self) -> None:
        raise NotImplementedError("架构 B：待商业化阶段实现")
