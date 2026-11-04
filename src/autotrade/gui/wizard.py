"""配置向导主窗口：分步收集配置 → TG 登录 → 固定群验证 → 交易所 → 保存自检。

信号群由开发者锁定（constants.GROUP_CHAT_TITLE），不允许自定义——防止
软件被用于监听其他群。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import tkinter as tk
from tkinter import ttk

from ruamel.yaml import YAML

from .. import paths
from ..constants import GROUP_CHAT_TITLE
from ..exchange.schemas import EXCHANGE_ORDER, EXCHANGE_SCHEMAS
from ..signal_source.telegram_userbot import TelegramUserbotSource
from .dialogs import GuiPrompter, show_error, show_info


class Wizard:
    """Tkinter 多步配置向导。run() 进入主循环，保存成功后销毁窗口。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("加密林教头VIP跟单助手 — 首次配置")
        self.root.geometry("600x520")
        self.root.minsize(560, 480)
        self.prompter = GuiPrompter(self.root)

        # 收集的配置
        self.api_id = tk.StringVar()
        self.api_hash = tk.StringVar()
        self.exchange_name = tk.StringVar(value="bybit")  # 所选交易所（schema key）
        self.exchange_fields: dict[str, tk.StringVar] = {}  # 动态字段 key -> var
        self.ex_notes = tk.StringVar()
        self.order_multiplier = tk.StringVar(value="1")  # 下单倍数（R 值缩放）
        self.tg_status = tk.StringVar(value="未登录")
        self.group_status = tk.StringVar(value=f"信号群（固定）：{GROUP_CHAT_TITLE}")
        self.group_ok = False

        self.saved = False
        self._build_ui()
        self.root.after(100, self._poll_prompt)

    # ---- UI 构建 ----

    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        nb.add(self._tab_welcome(nb), text="1 欢迎")
        nb.add(self._tab_telegram(nb), text="2 Telegram")
        nb.add(self._tab_exchange(nb), text="3 交易所")
        nb.add(self._tab_finish(nb), text="4 完成")

    def _tab_welcome(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="欢迎使用 加密林教头VIP跟单助手",
                  font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Label(f, wraplength=520, justify="left", text=(
            "本工具会在你的电脑上登录你自己的 Telegram 账号，监听私密信号群的报单，"
            "并自动在你的交易所账户跟单（下单、挂止损止盈、移损、平仓）。\n\n"
            "开始前请准备好：\n"
            "  1. TG 的 api_id 与 api_hash（到 https://my.telegram.org 申请）\n"
            "  2. 交易所的 API Key 与 Secret（Bybit，仅开「读写 + 合约交易」权限，不要开提现）\n\n"
            "所有配置只保存在你的电脑本地，不会上传。"
        )).pack(anchor="w")
        return f

    def _tab_telegram(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="填写 Telegram API 并登录", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(f, text="api_id").pack(anchor="w")
        ttk.Entry(f, textvariable=self.api_id, width=40).pack(anchor="w", pady=(0, 8))

        ttk.Label(f, text="api_hash").pack(anchor="w")
        ttk.Entry(f, textvariable=self.api_hash, width=40).pack(anchor="w", pady=(0, 12))

        ttk.Button(f, text="登录 Telegram", command=self._login_tg).pack(anchor="w")
        ttk.Label(f, textvariable=self.tg_status, foreground="#2563EB").pack(anchor="w", pady=(8, 12))

        ttk.Label(f, textvariable=self.group_status,
                  foreground="#2563EB").pack(anchor="w")
        ttk.Label(f, foreground="#64748B", justify="left", wraplength=520, text=(
            "信号群由开发者固定，不可修改。登录后自动验证你的账号是否已加入该群；"
            "未加入或被移出群后，软件将无法使用。"
        )).pack(anchor="w", pady=(6, 0))
        return f

    def _tab_exchange(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="选择你的交易所并填写 API（你自己的账户）",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(f, text="交易所").pack(anchor="w")
        combo = ttk.Combobox(f, textvariable=self.exchange_name, state="readonly",
                             values=EXCHANGE_ORDER, width=40)
        combo.pack(anchor="w", pady=(0, 10))
        combo.bind("<<ComboboxSelected>>", lambda e: self._render_exchange_fields())

        # 动态字段区 + 注意事项区（随所选交易所重建）
        self._fields_frame = ttk.Frame(f)
        self._fields_frame.pack(anchor="w", fill="x", pady=(0, 6))
        self._notes_label = ttk.Label(f, textvariable=self.ex_notes,
                                      foreground="#B45309", wraplength=520, justify="left")
        self._notes_label.pack(anchor="w", pady=(6, 0))

        self._render_exchange_fields()
        return f

    def _render_exchange_fields(self) -> None:
        """按 EXCHANGE_SCHEMAS 重建所选交易所的字段与注意事项。"""
        for w in self._fields_frame.winfo_children():
            w.destroy()
        schema = EXCHANGE_SCHEMAS[self.exchange_name.get()]
        self.exchange_fields = {}
        for field in schema["fields"]:
            row = ttk.Frame(self._fields_frame)
            row.pack(anchor="w", fill="x", pady=(0, 6))
            ttk.Label(row, text=field["label"], width=22).pack(side="left")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=40,
                      show="*" if field["secret"] else "").pack(side="left")
            self.exchange_fields[field["key"]] = var
        self.ex_notes.set("注意事项：\n" + "\n".join(
            f"• {n}" for n in schema["notes"]
        ))

    def _tab_finish(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="风控与保存", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(f)
        row.pack(anchor="w", pady=(0, 10))
        ttk.Label(row, text="下单倍数").pack(side="left")
        ttk.Combobox(row, textvariable=self.order_multiplier, state="readonly",
                     values=("0.25", "0.5", "1", "2", "3", "5"),
                     width=8).pack(side="left", padx=(8, 0))

        ttk.Label(f, foreground="#475569", wraplength=520, justify="left", text=(
            "报单「控仓维持 x% 风控」的 R 值乘以下单倍数：\n"
            "1 倍 = 按报单原值（如 2%）；0.5 倍 = 减半（1%）；2 倍 = 加倍（4%）。\n"
            "手数低于交易所最低手数时，自动按最低手数 × TP 档数下单（保证每档都能出场）；\n"
            "高于最高手数时按最高手数下单。\n"
            "默认风控：最多 3 个并发持仓、单日亏损上限 5%。\n"
            "保存前会自动检测 TG 登录与交易所连通性。"
        )).pack(anchor="w", pady=(10, 0))
        ttk.Button(f, text="保存并自检", command=self._save_and_verify).pack(anchor="w", pady=20)
        return f

    # ---- 轮询 ----

    def _poll_prompt(self) -> None:
        self.prompter.poll()
        self.root.after(100, self._poll_prompt)

    # ---- TG 登录（后台 asyncio）----

    def _make_source(self) -> TelegramUserbotSource:
        return TelegramUserbotSource(
            handler=lambda raw: None,
            api_id=int(self.api_id.get() or 0),
            api_hash=self.api_hash.get().strip(),
            session_name=paths.session_path("autotrade_session"),
            proxy=None,  # 自动检测系统代理
            prompt=self.prompter.prompt,
        )

    def _login_tg(self) -> None:
        if int(self.api_id.get() or 0) <= 0 or not self.api_hash.get().strip():
            show_error(self.root, "错误", "请先填写 TG 的 api_id 和 api_hash")
            return
        self.tg_status.set("登录中…")

        def _run():
            try:
                src = self._make_source()

                async def _flow():
                    """同一事件循环内完成 登录 + 群权限验证（Telethon 客户端禁止跨循环复用）。"""
                    me = await src.login()
                    ok, msg = await src.check_group_access()
                    return me, ok, msg

                me, ok, msg = asyncio.run(_flow())
                name = f"{me.first_name or ''} (@{me.username or ''})".strip()
                self.root.after(0, lambda: self.tg_status.set(f"已登录：{name}"))
                self.group_ok = ok
                self.root.after(0, lambda: self.group_status.set(
                    f"✅ {msg}" if ok else f"❌ {msg}"
                ))
            except Exception as e:  # noqa: BLE001
                logging.getLogger("autotrade").exception("TG 登录流程失败")
                self.root.after(0, lambda: self.tg_status.set(f"登录失败：{e}"))

        threading.Thread(target=_run, daemon=True).start()

    # ---- 保存 + 自检 ----

    def _save_and_verify(self) -> None:
        if not self.api_id.get().strip() or not self.api_hash.get().strip():
            show_error(self.root, "错误", "请填写 TG 的 api_id 和 api_hash")
            return
        schema = EXCHANGE_SCHEMAS[self.exchange_name.get()]
        missing = [f["label"] for f in schema["fields"]
                   if not (self.exchange_fields.get(f["key"]) or tk.StringVar(value="")).get().strip()]
        if missing:
            show_error(self.root, "错误", "请填写交易所的：" + "、".join(missing))
            return

        def _run():
            errors = []
            # TG 自检 + 固定群权限验证（同一事件循环内完成，避免跨循环复用客户端）
            try:
                src = self._make_source()

                async def _tg_check():
                    if not await src.check_authorized():
                        return "TG 未登录：请先在「Telegram」页完成登录"
                    ok, msg = await src.check_group_access()
                    if not ok:
                        return msg
                    return ""

                err = asyncio.run(_tg_check())
                if err:
                    errors.append(err)
            except Exception as e:  # noqa: BLE001
                logging.getLogger("autotrade").exception("TG 自检失败")
                errors.append(f"TG 自检失败：{e}")

            # 交易所自检（动态：按所选交易所构造适配器）
            try:
                from ..exchange.factory import get_adapter
                api_cfg = {k: v.get().strip() for k, v in self.exchange_fields.items()}
                adapter = get_adapter(self.exchange_name.get(), api_cfg)
                equity = asyncio.run(adapter.fetch_equity())
                if equity is None:
                    errors.append("交易所余额读取异常")
            except Exception as e:  # noqa: BLE001
                errors.append(f"交易所自检失败：{e}")

            if errors:
                self.root.after(0, lambda: show_error(self.root, "自检未通过", "\n".join(errors)))
                return

            try:
                self._write_config()
                self.saved = True
                self.root.after(0, self._on_saved)
            except Exception as e:  # noqa: BLE001
                self.root.after(0, lambda: show_error(self.root, "保存失败", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _write_config(self) -> None:
        paths.ensure_dirs()
        # 只写所选交易所的字段，其余留空
        ex_cfg = {name: {"apiKey": "", "secret": "", "password": ""}
                  for name in EXCHANGE_ORDER}
        selected = {k: v.get().strip() for k, v in self.exchange_fields.items()}
        for k, v in selected.items():
            ex_cfg[self.exchange_name.get()][k] = v
        cfg = {
            "telegram": {
                "session_name": "autotrade_session",
                "api_id": int(self.api_id.get().strip()),
                "api_hash": self.api_hash.get().strip(),
                # 信号群由开发者锁定（constants.py），不写入配置、不可自定义
                "proxy": {"enabled": False, "type": "socks5", "addr": "127.0.0.1", "port": 7890},
            },
            "dry_run": False,  # 面向真实用户：始终真实下单（下单倍数控制风险）
            "exchanges": {
                "active": self.exchange_name.get(),
                "proxy": {"enabled": False, "type": "http", "addr": "127.0.0.1", "port": 7897},
                **ex_cfg,
            },
            "risk": {
                "max_concurrent_positions": 3,
                "daily_loss_pct": 5.0,
                "max_slippage_pct": 0.3,
                "margin_formula_tol_pct": 0.1,
                "tp_ratios": "equal",
                "order_multiplier": float(self.order_multiplier.get() or "1"),
            },
            "analysts": {"allow_all": True, "list": []},
            "behavior": {
                "amend_sl_on_move": True,
                "close_on_manual_close": True,
                "cancel_symbol_orders_on_terminal": True,
            },
            "notify": {"send_to": ""},
            "storage": {"db_path": ""},
        }
        yaml = YAML()
        yaml.default_flow_style = False
        with open(paths.config_path(), "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

    def _on_saved(self) -> None:
        show_info(self.root, "配置完成", f"配置已保存到：\n{paths.config_path()}\n\n现在可以启动跟单了。")
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
