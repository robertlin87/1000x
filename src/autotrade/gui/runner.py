"""執行日誌視窗：背景啟動監聽，主執行緒滾動顯示日誌。"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from .. import main as autotrade_main
from .. import paths
from ..logfile import PrivacyFilter


class _TkLogHandler(logging.Handler):
    """把日誌記錄送入執行緒安全佇列，由主執行緒輪詢寫入 Text。"""

    def __init__(self, q: "queue.Queue[str]") -> None:
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class RunnerWindow:
    """執行視窗：背景執行緒跑監聽，主執行緒滾動顯示日誌。關閉視窗即停止。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("加密林教頭 VIP跟單助手")
        self.root.geometry("780x540")
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._build_ui()
        self._install_logger()
        self.root.after(100, self._poll_log)
        self._start_listening()

    def _build_ui(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="重新設定", command=self._reconfigure).pack(side="left")
        ttk.Button(bar, text="匯出問題報告", command=self._export_report).pack(side="left", padx=(8, 0))
        ttk.Label(bar, text="關閉視窗即停止跟單", foreground="#475569").pack(side="right")

        self.text = scrolledtext.ScrolledText(
            self.root, state="disabled", font=("Consolas", 9), wrap="word"
        )
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _install_logger(self) -> None:
        handler = _TkLogHandler(self._log_q)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(PrivacyFilter())
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
                logging.getLogger("autotrade").exception("監聽異常退出")

        threading.Thread(target=_target, daemon=True).start()

    def _reconfigure(self) -> None:
        """刪除設定並關閉視窗，使用者重新開啟應用程式即進入精靈。"""
        try:
            paths.config_path().unlink(missing_ok=True)
        except OSError:
            pass
        self.root.destroy()

    def _export_report(self) -> None:
        """產生問題報告並開啟 temp 資料夾，使用者把 txt 發給對接人。"""
        import os

        from ..report import write_report_file
        from .dialogs import show_error, show_info

        def _run():
            try:
                path = write_report_file()
                self.root.after(0, lambda: self._on_report_ready(path))
            except Exception as e:  # noqa: BLE001
                logging.getLogger("autotrade").exception("產生問題報告失敗")
                self.root.after(0, lambda: show_error(self.root, "失敗", f"產生報告失敗：{e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_report_ready(self, path) -> None:
        import os

        from .dialogs import show_info

        show_info(self.root, "問題報告已產生",
                  f"請把下面這個檔案發給你的對接人：\n{path}")
        try:
            os.startfile(str(paths.temp_dir()))  # 開啟 temp 資料夾方便使用者找檔案
        except OSError:
            pass

    def run(self) -> None:
        self.root.mainloop()
