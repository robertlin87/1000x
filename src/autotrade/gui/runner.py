"""运行日志窗口：后台启动监听，主线程滚动显示日志。"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from .. import main as autotrade_main
from .. import paths


class _TkLogHandler(logging.Handler):
    """把日志记录送入线程安全队列，由主线程轮询写入 Text。"""

    def __init__(self, q: "queue.Queue[str]") -> None:
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class RunnerWindow:
    """运行窗口：后台线程跑监听，主线程滚动显示日志。关闭窗口即停止。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AutoTrade 跟单助手")
        self.root.geometry("780x540")
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._build_ui()
        self._install_logger()
        self.root.after(100, self._poll_log)
        self._start_listening()

    def _build_ui(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="重新配置", command=self._reconfigure).pack(side="left")
        ttk.Label(bar, text="关闭窗口即停止跟单", foreground="#475569").pack(side="right")

        self.text = scrolledtext.ScrolledText(
            self.root, state="disabled", font=("Consolas", 9), wrap="word"
        )
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _install_logger(self) -> None:
        handler = _TkLogHandler(self._log_q)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger = logging.getLogger("autotrade")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logging.getLogger("telethon").setLevel(logging.WARNING)

    def _poll_log(self) -> None:
        while True:
            try:
                line = self._log_q.get_nowait()
            except queue.Empty:
                break
            self.text.configure(state="normal")
            self.text.insert("end", line + "\n")
            self.text.see("end")
            self.text.configure(state="disabled")
        self.root.after(100, self._poll_log)

    def _start_listening(self) -> None:
        def _target() -> None:
            try:
                asyncio.run(autotrade_main.run())
            except Exception:  # noqa: BLE001
                logging.getLogger("autotrade").exception("监听异常退出")

        threading.Thread(target=_target, daemon=True).start()

    def _reconfigure(self) -> None:
        """删除配置并关闭窗口，用户重新打开应用即进入向导。"""
        try:
            paths.config_path().unlink(missing_ok=True)
        except OSError:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
