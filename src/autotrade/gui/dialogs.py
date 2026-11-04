"""GUI 对话框：跨线程提示弹窗。

信号群由开发者锁定（constants.py），无群选择对话框。
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, simpledialog


class GuiPrompter:
    """跨线程提示器：后台线程调 prompt() 时，经 queue 请求主线程弹窗。

    用法：主线程周期调 poll()（用 root.after）；后台 asyncio 里
    await to_thread(prompter.prompt, text) 会阻塞等待用户在主线程弹窗输入。
    """

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._req: queue.Queue[str] = queue.Queue()
        self._res: queue.Queue[str] = queue.Queue()

    def prompt(self, text: str) -> str:
        """同步阻塞：请求主线程弹窗，返回用户输入（可为空字符串）。"""
        self._req.put(text)
        return self._res.get()

    def poll(self) -> None:
        """主线程周期调用，处理待弹窗请求。"""
        try:
            text = self._req.get_nowait()
        except queue.Empty:
            return
        result = simpledialog.askstring("请输入", text, parent=self._root)
        self._res.put(result or "")


def show_error(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showerror(title, msg, parent=root)


def show_info(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showinfo(title, msg, parent=root)
