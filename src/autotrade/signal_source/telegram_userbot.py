"""架构 A 信号源：Telethon userbot。

同时监听两个事件通道：
- NewMessage：报单新消息 + 手工操作紧凑通知（如「📌訂單 188 … 🟥 已平倉」）
- MessageEdited：原报单被编辑（操作記錄追加行）

被踢出私密群后 Telegram 停止推送，软件自然失效（群资格即授权）。
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime

from telethon import TelegramClient, events

from ..proxy import resolve_proxy
from .base import MessageHandler, RawMessage, SignalSource

log = logging.getLogger("autotrade.signal_source.userbot")


def _build_proxy(proxy_cfg: dict | None):
    """把 config 的 proxy 段解析成 Telethon 代理参数。

    enabled=true 显式用 config 的 type/addr/port；enabled=false 自动读 Windows
    系统代理（解决端口写死、VPN 重启端口变化问题）；都无则 None（直连）。
    Telethon 1.45+ 的 proxy_type 用字符串 "http"/"socks5"，代理建立需要 python_socks。
    """
    return resolve_proxy(proxy_cfg, default_type="socks5")


def _patch_keepalive_interval(interval: float = 30.0) -> None:
    """把 Telethon 的 keepalive ping 间隔从默认 60s 降到 interval 秒。

    经本地代理（如 127.0.0.1:7897）连 TG 时，代理对空闲长连接约 60s 超时，
    而 Telethon 默认 60s 才 ping 一次，两者撞车导致连接每 60s 被代理断开
    （日志刷 "Server closed the connection"）。把 ping 间隔降到 30s 保持连接
    活跃，避免被代理断开。只 patch 一次，重复调用无副作用。
    """
    if getattr(TelegramClient, "_autotrade_patched_keepalive", False):
        return

    async def _keepalive_loop(self):
        rnd = lambda: random.randrange(-2**63, 2**63)
        while self.is_connected():
            try:
                await asyncio.wait_for(self.disconnected, timeout=interval)
                continue
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                return
            except Exception:
                continue
            await self._clean_exported_senders()
            if not self._sender._transport_connected():
                continue
            try:
                self._sender._keepalive_ping(rnd())
            except (ConnectionError, asyncio.CancelledError):
                return

    TelegramClient._keepalive_loop = _keepalive_loop
    TelegramClient._autotrade_patched_keepalive = True


class TelegramUserbotSource(SignalSource):
    """Telethon userbot 信号源。

    :param chat_title: 按群名定位（推荐，可读性好）
    :param chat_id: 按 chat id 定位（优先于 chat_title，避免重名群）
    """

    def __init__(
        self,
        handler: MessageHandler,
        api_id: int,
        api_hash: str,
        session_name: str = "autotrade_session",
        chat_title: str | None = None,
        chat_id: int | None = None,
        proxy: dict | None = None,
        prompt: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(handler)
        _patch_keepalive_interval()
        if api_id <= 0 or not api_hash:
            raise ValueError(
                "api_id/api_hash 未配置：请到 https://my.telegram.org 申请，"
                "填入 config/config.yaml 的 telegram 段"
            )
        self._client = TelegramClient(
            session_name, api_id, api_hash, proxy=_build_proxy(proxy)
        )
        self._prompt = prompt or input  # 可注入的提示回调（GUI 弹窗 / 命令行 input）
        self._chat_title = chat_title
        self._chat_id = chat_id
        self._target = None

    # ---- 公开入口 ----

    async def login(self):
        """首次交互登录（中文引导：手机号+验证码+2FA），成功后会话保存在本地 session 文件。

        验证码会发到你的 Telegram（app 通知或短信）；若账号开了两步验证（2FA），
        还需输入一次密码。登录过一次后 session 文件持久有效，无需重复登录。
        返回 me 信息（已登录或登录成功）供 GUI 显示账号名。
        """
        from telethon.errors import SessionPasswordNeededError

        await self._client.connect()
        if await self._client.is_user_authorized():
            me = await self._client.get_me()
            log.info("已登录过：%s (@%s)，无需重复登录", me.first_name, me.username)
            await self._client.disconnect()
            return me
        phone = (await asyncio.to_thread(
            self._prompt, "请输入 TG 手机号（国际格式带国家区号，如 +852 12345678）："
        )).strip()
        await self._client.send_code_request(phone)
        code = (await asyncio.to_thread(
            self._prompt, "请输入 Telegram 收到的登录验证码："
        )).strip()
        try:
            await self._client.sign_in(phone, code)
        except SessionPasswordNeededError:
            pwd = await asyncio.to_thread(
                self._prompt, "账号开启了两步验证（2FA），请输入密码："
            )
            await self._client.sign_in(password=pwd)
        me = await self._client.get_me()
        log.info("登录成功：%s (@%s)，会话已保存", me.first_name, me.username)
        await self._client.disconnect()
        return me

    async def check_authorized(self) -> bool:
        """检查 TG 是否已登录（connect → is_user_authorized → disconnect）。"""
        await self._client.connect()
        try:
            return await self._client.is_user_authorized()
        finally:
            await self._client.disconnect()

    async def list_dialogs(self, limit: int = 50) -> list[tuple[str, int]]:
        """列出最近的群/频道（群名, chat id），用于定位信号群。"""
        await self._client.start()
        out: list[tuple[str, int]] = []
        async for d in self._client.iter_dialogs(limit=limit):
            if d.is_group or d.is_channel:
                out.append((d.name or "", d.id))
        return out

    async def start(self) -> None:
        await self._client.start()
        me = await self._client.get_me()
        log.info("已登录 TG：%s (id=%s, @%s)", me.first_name, me.id, me.username)

        self._target = await self._resolve_chat()
        self._check_group_privacy()
        self._register_handlers()
        log.info("开始监听群「%s」，Ctrl+C 退出", getattr(self._target, "title", self._target))
        await self._client.run_until_disconnected()

    async def stop(self) -> None:
        await self._client.disconnect()

    # ---- 内部 ----

    async def _resolve_chat(self):
        if self._chat_id:
            return await self._client.get_entity(int(self._chat_id))
        if self._chat_title:
            async for d in self._client.iter_dialogs():
                if d.name == self._chat_title:
                    return d.entity
        raise RuntimeError(
            "找不到目标群：请确认 config.yaml 的 chat_title 与群名完全一致，"
            "或先运行 `python scripts/listen.py --list` 查看会话列表"
        )

    def _check_group_privacy(self) -> None:
        # 私密群前提：公开群被踢后仍可轮询历史，群资格授权会被绕过
        username = getattr(self._target, "username", None)
        if username:
            log.warning(
                "⚠️ 目标群是公开群（@%s）：被踢出后仍可读到历史消息，授权模型不成立，建议改用私密群",
                username,
            )

    def _register_handlers(self) -> None:
        target = self._target

        @self._client.on(events.NewMessage(chats=target))
        async def _on_new(event):
            if event.message.text:
                await self._dispatch(event, is_edit=False)

        @self._client.on(events.MessageEdited(chats=target))
        async def _on_edit(event):
            if event.message.text:
                await self._dispatch(event, is_edit=True)

    async def _dispatch(self, event, is_edit: bool) -> None:
        msg = event.message
        raw = RawMessage(
            chat_id=event.chat_id or 0,
            chat_title=getattr(event.chat, "title", ""),
            sender_id=msg.sender_id,
            msg_id=msg.id,
            text=msg.text,
            ts=msg.date.isoformat(timespec="seconds") if msg.date else datetime.now().isoformat(timespec="seconds"),
            is_edit=is_edit,
        )
        await self._handler(raw)
