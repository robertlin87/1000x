"""配置向导主窗口：分步收集配置 → TG 登录 → 群选择 → 保存自检。"""
from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from tkinter import ttk

from ruamel.yaml import YAML

from .. import paths
from ..signal_source.telegram_userbot import TelegramUserbotSource
from .dialogs import GuiPrompter, choose_chat, show_error, show_info


class Wizard:
    """Tkinter 多步配置向导。run() 进入主循环，保存成功后销毁窗口。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AutoTrade 跟单助手 — 首次配置")
        self.root.geometry("600x520")
        self.root.minsize(560, 480)
        self.prompter = GuiPrompter(self.root)

        # 收集的配置
        self.api_id = tk.StringVar()
        self.api_hash = tk.StringVar()
        self.chat_id = tk.StringVar()
        self.bybit_key = tk.StringVar()
        self.bybit_secret = tk.StringVar()
        self.testnet = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        self.tg_status = tk.StringVar(value="未登录")

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
        ttk.Label(f, text="欢迎使用 AutoTrade 跟单助手",
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

        ttk.Label(f, text="信号群 chat_id（可点下方「选择群聊」自动填入）").pack(anchor="w")
        ttk.Entry(f, textvariable=self.chat_id, width=40).pack(anchor="w", pady=(0, 8))
        ttk.Button(f, text="选择群聊", command=self._list_chats).pack(anchor="w")
        return f

    def _tab_exchange(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="填写 Bybit API（用户自己的账户）",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(f, text="API Key").pack(anchor="w")
        ttk.Entry(f, textvariable=self.bybit_key, width=45).pack(anchor="w", pady=(0, 8))

        ttk.Label(f, text="Secret").pack(anchor="w")
        ttk.Entry(f, textvariable=self.bybit_secret, width=45, show="*").pack(anchor="w", pady=(0, 12))

        ttk.Checkbutton(f, text="使用 testnet 测试网（推荐首次使用先开）",
                        variable=self.testnet).pack(anchor="w")
        ttk.Label(f, foreground="#B45309", wraplength=520, justify="left", text=(
            "提醒：API Key 请开「读写 + 合约交易」权限，切勿开「提现」；"
            "充值后需在 Bybit 里把资金从「资金账户」划转到「统一交易账户」。"
        )).pack(anchor="w", pady=(10, 0))
        return f

    def _tab_finish(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=20)
        ttk.Label(f, text="风控与保存", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Checkbutton(f, text="试运行（每笔只下最小手数，验证用，推荐首次开启）",
                        variable=self.dry_run).pack(anchor="w")
        ttk.Label(f, foreground="#475569", wraplength=520, justify="left", text=(
            "默认风控：最多 3 个并发持仓、单日亏损上限 5%、每笔按最小手数×TP档数下单。\n"
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
                me = asyncio.run(self._make_source().login())
                name = f"{me.first_name or ''} (@{me.username or ''})".strip()
                self.root.after(0, lambda: self.tg_status.set(f"已登录：{name}"))
            except Exception as e:  # noqa: BLE001
                self.root.after(0, lambda: self.tg_status.set(f"登录失败：{e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _list_chats(self) -> None:
        if int(self.api_id.get() or 0) <= 0 or not self.api_hash.get().strip():
            show_error(self.root, "错误", "请先填写 TG 的 api_id 和 api_hash")
            return

        def _run():
            try:
                src = self._make_source()
                dialogs = asyncio.run(src.list_dialogs())
                self.root.after(0, lambda: self._on_dialogs(dialogs))
            except Exception as e:  # noqa: BLE001
                self.root.after(0, lambda: show_error(self.root, "错误", f"列出群聊失败：{e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_dialogs(self, dialogs: list[tuple[str, int]]) -> None:
        chat_id = choose_chat(self.root, dialogs)
        if chat_id:
            self.chat_id.set(chat_id)

    # ---- 保存 + 自检 ----

    def _save_and_verify(self) -> None:
        if not self.api_id.get().strip() or not self.api_hash.get().strip():
            show_error(self.root, "错误", "请填写 TG 的 api_id 和 api_hash")
            return
        if not self.bybit_key.get().strip() or not self.bybit_secret.get().strip():
            show_error(self.root, "错误", "请填写 Bybit 的 API Key 和 Secret")
            return

        def _run():
            errors = []
            # TG 自检
            try:
                src = self._make_source()
                if not asyncio.run(src.check_authorized()):
                    errors.append("TG 未登录：请先在「Telegram」页完成登录")
            except Exception as e:  # noqa: BLE001
                errors.append(f"TG 自检失败：{e}")

            # 交易所自检
            try:
                from ..exchange.factory import get_adapter
                adapter = get_adapter("bybit", {
                    "apiKey": self.bybit_key.get().strip(),
                    "secret": self.bybit_secret.get().strip(),
                    "testnet": self.testnet.get(),
                })
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
        cfg = {
            "telegram": {
                "session_name": "autotrade_session",
                "api_id": int(self.api_id.get().strip()),
                "api_hash": self.api_hash.get().strip(),
                "chat_title": "",
                "chat_id": int(self.chat_id.get().strip()) if self.chat_id.get().strip() else 0,
                "proxy": {"enabled": False, "type": "socks5", "addr": "127.0.0.1", "port": 7890},
            },
            "dry_run": self.dry_run.get(),
            "exchanges": {
                "active": "bybit",
                "proxy": {"enabled": False, "type": "http", "addr": "127.0.0.1", "port": 7897},
                "bybit": {
                    "apiKey": self.bybit_key.get().strip(),
                    "secret": self.bybit_secret.get().strip(),
                    "testnet": self.testnet.get(),
                },
                "bitget": {"apiKey": "", "secret": "", "password": ""},
                "deepcoin": {"apiKey": "", "secret": ""},
                "bitunix": {"apiKey": "", "secret": ""},
            },
            "risk": {
                "max_concurrent_positions": 3,
                "daily_loss_pct": 5.0,
                "max_slippage_pct": 0.3,
                "margin_formula_tol_pct": 0.1,
                "tp_ratios": "equal",
                "trial_min_qty": True,
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
