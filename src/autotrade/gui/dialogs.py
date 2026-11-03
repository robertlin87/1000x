"""GUI 对话框：跨线程提示弹窗、群选择对话框。"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


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


def choose_chat(root: tk.Misc, dialogs: list[tuple[str, int]]) -> str | None:
    """弹出群选择对话框，返回所选群名对应的 chat_id 字符串，取消返回 None。"""
    if not dialogs:
        messagebox.showinfo("提示", "未找到任何群聊。", parent=root)
        return None

    top = tk.Toplevel(root)
    top.title("选择信号群")
    top.transient(root)
    top.grab_set()
    top.geometry("420x360")

    ttk.Label(top, text="请选择你要跟单的信号群：", padding=8).pack(anchor="w")

    frame = ttk.Frame(top)
    frame.pack(fill="both", expand=True, padx=8, pady=4)

    listbox = tk.Listbox(frame, font=("Microsoft YaHei UI", 10))
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    listbox.pack(side="left", fill="both", expand=True)

    for name, _cid in dialogs:
        listbox.insert("end", f"{name}  ({_cid})")

    result: dict[str, str | None] = {"value": None}

    def _on_ok():
        sel = listbox.curselection()
        if sel:
            name, chat_id = dialogs[sel[0]]
            result["value"] = str(chat_id)
        top.destroy()

    def _on_cancel():
        top.destroy()

    btn = ttk.Frame(top)
    btn.pack(fill="x", padx=8, pady=8)
    ttk.Button(btn, text="确定", command=_on_ok).pack(side="right", padx=4)
    ttk.Button(btn, text="取消", command=_on_cancel).pack(side="right")

    top.wait_window()
    return result["value"]


def show_error(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showerror(title, msg, parent=root)


def show_info(root: tk.Misc, title: str, msg: str) -> None:
    messagebox.showinfo(title, msg, parent=root)
