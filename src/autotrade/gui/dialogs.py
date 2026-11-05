"""GUI 對話方塊：跨執行緒提示彈窗。

訊號群由開發者鎖定（constants.py），無群選擇對話方塊。
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, simpledialog


class GuiPrompter:
    """跨執行緒提示器：背景執行緒呼叫 prompt() 時，經由 queue 請求主執行緒彈窗。

    用法：主執行緒週期呼叫 poll()（用 root.after）；背景 asyncio 裡
    await to_thread(prompter.prompt, text) 會阻塞等待使用者在主執行緒彈窗輸入。
    """

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._req: queue.Queue[str] = queue.Queue()
        self._res: queue.Queue[str] = queue.Queue()

    def prompt(self, text: str) -> str:
        """同步阻塞：請求主執行緒彈窗，返回使用者輸入（可為空字串）。"""
        self._req.put(text)
        return self._res.get()

    def poll(self) -> None:
        """主執行緒週期呼叫，處理待彈窗請求。"""
        try:
            text = self._req.get_nowait()
        except queue.Empty:
            return
        result = simpledialog.askstring("請輸入", text, parent=self._root)
        self._res.put(result or "")


def show_error(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showerror(title, msg, parent=root)


def show_info(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showinfo(title, msg, parent=root)
