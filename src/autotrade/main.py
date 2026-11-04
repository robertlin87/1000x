"""主程序装配：双通道消息 → 三类解析器 → SQLite 统一事件层 → TriggerRouter → 执行。

主触发（价格）由 M2 交易所挂单承担；本层是备份核对与人为指令通道。
数据流：Userbot(NewMessage+MessageEdited) → Entry/Notice/Op 解析器 →
signal_ops 幂等事件层 → TriggerRouter → OrderManager。
dry_run=true 时用 NoopAdapter（全链路不碰交易所），只记录通知。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from . import paths
from .config import load_config
from .exchange.factory import get_adapter
from .exchange.noop import NoopAdapter
from .execution.order_manager import OrderManager
from .execution.trigger_router import TriggerRouter
from .execution.watchdog import Watchdog
from .logfile import install_file_logging
from .notify.notifier import Notifier
from .parser.entry_parser import EntryParser
from .parser.notice_parser import NoticeParser
from .parser.op_parser import OpParser, modify_hash, op_line_hash
from .signal_source.base import RawMessage
from .signal_source.telegram_userbot import TelegramUserbotSource
from .storage.db import (add_signal_op, get_signal, init_db,
                         update_signal_fields, upsert_signal)

log = logging.getLogger("autotrade")


class MessagePipeline:
    """消息 → 事件：三类消息解析 + 统一事件层（幂等）→ router 触发动作。"""

    def __init__(self, db, notifier: Notifier, router=None) -> None:
        self._db = db
        self._notifier = notifier
        self._router = router  # TriggerRouter；None 表示纯 dry-run 记录
        self._entry = EntryParser()
        self._notice = NoticeParser()
        self._op = OpParser()

    async def handle(self, raw: RawMessage) -> None:
        """信号源入口。单条消息异常不得中断监听。"""
        try:
            if raw.is_edit:
                await self._handle_edit(raw)
            else:
                await self._handle_new(raw)
        except Exception:
            log.exception("消息处理失败 (msg_id=%s)：%s", raw.msg_id, raw.text[:80])

    # ---- 新消息通道：报单 or 紧凑通知 ----

    async def _handle_new(self, raw: RawMessage) -> None:
        signal = self._entry.parse(raw.text)
        if signal:
            await self._log_signal(raw, signal)
            return
        notice = self._notice.parse(raw.text)
        if notice:
            old_signal = None
            if notice.action_type == "modify":
                h = modify_hash(notice.mod_fields, notice.ts_text)
                old_signal = await get_signal(self._db, raw.chat_id, notice.order_id)
            else:
                h = op_line_hash(notice.action_type, notice.tp_index, notice.price)
            inserted = await add_signal_op(
                self._db, raw.chat_id, notice.order_id, h, notice.raw_text,
                source="notice", action_type=notice.action_type,
                tp_index=notice.tp_index, price=notice.price,
                ts_text=notice.ts_text,
            )
            if inserted:
                await self._notifier.send(
                    f"📌订单 {notice.order_id} {notice.symbol} "
                    f"{'做多' if notice.side == 'long' else '做空'} {notice.action_type}（notice 通道）"
                )
                if self._router:
                    await self._router.on_event(
                        notice.order_id, notice.symbol, notice.action_type,
                        notice.tp_index, notice.price,
                        mod_fields=notice.mod_fields, old_signal=old_signal,
                    )
                if notice.action_type == "modify":
                    await self._apply_modify_db(raw.chat_id, notice.order_id,
                                                old_signal, notice.mod_fields)
            else:
                log.info("重复事件（幂等忽略）：%s", notice.raw_text[:60])
            return
        log.info("未识别消息 (msg_id=%s)：%s", raw.msg_id, raw.text[:80].replace("\n", " ⏎ "))

    # ---- 编辑通道：报单 upsert + 操作行差量事件 ----

    async def _handle_edit(self, raw: RawMessage) -> None:
        signal = self._entry.parse(raw.text)
        if signal:
            sig_inserted = await upsert_signal(self._db, raw.chat_id, signal)
            if sig_inserted and self._router:
                await self._router.on_signal(signal)
        order_id = signal.order_id if signal else self._entry.extract_order_id(raw.text)
        for op in self._op.extract_ops(raw.text):
            if op.action_type == "ignore":
                continue
            if op.action_type == "unknown":
                # 未匹配行落库供模板补齐；每次编辑重复出现只记一次
                log.info("未匹配操作行（供模板补齐）：%s", op.line_text.strip()[:80])
                if order_id:
                    await add_signal_op(
                        self._db, raw.chat_id, order_id,
                        op_line_hash("unknown", None, None, op.line_text),
                        op.line_text, source="edit", action_type="unknown",
                        ts_text=op.ts_text,
                    )
                continue
            if not order_id:
                log.warning("操作行缺 order_id，跳过：%s", op.line_text.strip()[:80])
                continue
            old_signal = None
            if op.action_type == "modify":
                h = modify_hash(op.mod_fields, op.ts_text)
                old_signal = await get_signal(self._db, raw.chat_id, order_id)
            else:
                h = op_line_hash(op.action_type, op.tp_index, op.price)
            inserted = await add_signal_op(
                self._db, raw.chat_id, order_id, h, op.line_text,
                source="edit", action_type=op.action_type,
                tp_index=op.tp_index, price=op.price, ts_text=op.ts_text,
            )
            if inserted:
                detail = f" TP{op.tp_index}" if op.tp_index else ""
                price = f" @{op.price}" if op.price else ""
                await self._notifier.send(
                    f"✏️订单 {order_id} {op.action_type}{detail}{price}（edit 通道）"
                )
                if self._router:
                    symbol = signal.symbol if signal else None
                    await self._router.on_event(
                        order_id, symbol, op.action_type, op.tp_index, op.price,
                        mod_fields=op.mod_fields, old_signal=old_signal,
                    )
                if op.action_type == "modify":
                    await self._apply_modify_db(raw.chat_id, order_id,
                                                old_signal, op.mod_fields)
            else:
                log.info("重复事件（幂等忽略）：%s", op.line_text.strip()[:60])

    async def _apply_modify_db(self, chat_id: int, order_id: str, old_signal, mod_fields) -> None:
        """訂單修改后同步 signals 表的 tps/sl/entry（后续修改以此为旧值）。"""
        fields = mod_fields or {}
        new_tp_prices = [p for _, p in sorted(fields.get("tps") or [])]
        if not new_tp_prices and old_signal is not None:
            new_tp_prices = list(old_signal.tps)
        new_sl = fields.get("sl")
        if new_sl is None and old_signal is not None:
            new_sl = old_signal.sl
        new_entry = fields.get("entry")
        if new_entry is None and old_signal is not None:
            new_entry = old_signal.entry
        await update_signal_fields(self._db, chat_id, order_id,
                                   new_tp_prices, new_sl or 0.0, new_entry or 0.0)

    async def _log_signal(self, raw: RawMessage, signal) -> None:
        warnings = self._entry.validate(signal)
        inserted = await upsert_signal(self._db, raw.chat_id, signal)
        if not inserted:
            log.info("已知报单更新 raw_text：订单%s", signal.order_id)
            return
        text = (
            f"🆕新报单 订单{signal.order_id} {signal.symbol} "
            f"{'做多' if signal.side == 'long' else '做空'} entry={signal.entry} "
            f"{'掛單' if signal.is_limit else '現價'} SL={signal.sl} "
            f"TP={'/'.join(map(str, signal.tps))} 控倉{signal.risk_pct}% "
            f"分析師:{signal.analyst}"
        )
        if warnings:
            text += " ⚠️" + "; ".join(warnings)
        await self._notifier.send(text)
        if self._router:
            await self._router.on_signal(signal)


async def run(config_path: str | None = None) -> None:
    """启动跟单主程序。config_path 缺省时用外部目录的 config.yaml。"""
    paths.ensure_dirs()
    paths.cleanup_temp_dir()  # 每日清理：只保留当天的日志/报告
    install_file_logging()  # 日志落盘 temp/autotrade.log（问题报告的数据来源）
    config_path = config_path or str(paths.config_path())
    cfg = load_config(config_path)
    db_path = Path(cfg.storage.get("db_path", str(paths.db_path())))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await init_db(str(db_path))
    notifier = Notifier(dry_run=cfg.dry_run, send_to=cfg.notify.get("send_to"))

    # M2 执行层：dry_run 用 NoopAdapter（不碰交易所），否则接真实交易所
    if cfg.dry_run:
        adapter = NoopAdapter()
    else:
        ex = cfg.exchanges
        active = ex.get("active", "bybit")
        adapter = get_adapter(active, ex.get(active, {}), proxy=ex.get("proxy"))
    order_manager = OrderManager(adapter)
    router = TriggerRouter(adapter, order_manager, notifier, cfg.risk, cfg.analysts)

    pipeline = MessagePipeline(db, notifier, router)

    # 看护轮询（无状态，交易所为唯一事实源）：止损/末档 TP 全平后清理残留挂单
    watchdog_task = None
    if not cfg.dry_run:
        watchdog = Watchdog(
            adapter, notifier,
            interval=float(cfg.risk.get("watchdog_interval_sec", 30.0)),
        )
        watchdog_task = asyncio.create_task(watchdog.run())

    tg = cfg.telegram
    # 信号群由 constants 锁定（开发者固定），忽略配置文件里的 chat_title/chat_id
    source = TelegramUserbotSource(
        handler=pipeline.handle,
        api_id=int(tg.get("api_id", 0)),
        api_hash=tg.get("api_hash", ""),
        session_name=paths.session_path(tg.get("session_name", "autotrade_session")),
        proxy=tg.get("proxy"),
    )
    try:
        await source.start()
    finally:
        if watchdog_task:
            watchdog_task.cancel()
            await asyncio.gather(watchdog_task, return_exceptions=True)
        await db.close()
