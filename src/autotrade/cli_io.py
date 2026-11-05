"""公共 CLI 按鍵/輸入工具：CLI 設定向導與乘數詢問共用。

設計要點：
- 輸入一律走這裡，便於單測 mock（multiplier_prompt / cli_setup 都從這裡取原語）。
- Windows 控制檯下 read_text 逐字符讀取，支持退格與 ESC（返回 None = 取消）；
  非 Windows / 非交互環境退回 input()/getpass()（ESC 不支持，單測直接 mock 本函數）。
- 不在此處引入任何日誌輸出，避免與外部 logging 設定打架。
"""
from __future__ import annotations

import getpass
import sys


def is_interactive() -> bool:
    """stdin 是否為可交互終端（被腳本重定向時返回 False）。"""
    return bool(sys.stdin.isatty())


def read_key() -> bytes:
    """讀單個按鍵（Windows 控制檯不等待回車），用於選單與 ESC 捕獲。

    非 Windows（與單測）退回讀一個字符；EOF 退回回車。
    """
    if sys.platform == "win32":
        import msvcrt

        return msvcrt.getch()
    ch = sys.stdin.read(1)
    return ch.encode(sys.stdin.encoding or "utf-8", "replace") or b"\r"


def read_line(prompt: str = "") -> str:
    return input(prompt)


def read_secret(prompt: str = "") -> str:
    return getpass.getpass(prompt)


def read_text(
    prompt: str, *, secret: bool = False, allow_esc: bool = True
) -> str | None:
    """讀一行文本，返回使用者輸入；使用者按 ESC（僅 Windows 控制檯）返回 None 表示取消。

    非 Windows / 非交互環境退回 input()/getpass()（ESC 不被支持，EOF/中斷返回 None）。
    """
    if sys.platform != "win32" or not sys.stdin.isatty():
        try:
            return read_secret(prompt) if secret else read_line(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    import msvcrt

    buf: list[str] = []
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            return "".join(buf)
        if ch == "\x1b":  # ESC
            if allow_esc:
                sys.stdout.write("\n")
                return None
            continue
        if ch in ("\b", "\x7f"):  # 退格
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch in ("\x00", "\xe0"):  # 功能鍵前綴，吞掉後續字節
            msvcrt.getwch()
            continue
        if ord(ch) < 0x20 and ch != "\t":  # 忽略其餘控制字符
            continue
        buf.append(ch)
        sys.stdout.write("*" if secret else ch)
        sys.stdout.flush()


def choose_from_list(
    options: list[str],
    *,
    title: str | None = None,
    prompt: str = "請輸入數字選擇（ESC 取消）：",
) -> int | None:
    """數字選單：列出選項供使用者填數字選擇。返回下標；ESC/取消返回 None。"""
    if title:
        print(title)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = read_text(prompt, allow_esc=True)
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            continue
        try:
            idx = int(raw) - 1
        except ValueError:
            print("  請輸入數字。")
            continue
        if 0 <= idx < len(options):
            return idx
        print("  數字超出範圍。")


def read_menu_key() -> bytes:
    """讀選單單鍵：1/2/3、回車、ESC。"""
    while True:
        k = read_key()
        if k in (b"1", b"2", b"3", b"\r", b"\n", b"\x1b"):
            return k
