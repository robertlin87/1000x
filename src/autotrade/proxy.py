"""網絡連線解析：優先 config 顯式設定，否則自動探測可用端口，否則直連。

解決「端口寫死」問題：本機網絡設定變化後端口會變，寫死端口會導致連不上。
自動檢測採用**探測式**：先探測已記錄的端口，不可用再掃常見端口，
找到可用端口才使用——端口變化自動跟上，零設定。

注意：本模塊不輸出任何日誌。本機網絡連線細節屬於環境信息，
不應出現在使用者可見視窗或導出的問題報告裡。
"""
from __future__ import annotations

import logging
import socket

log = logging.getLogger("autotrade.proxy")

# 常見本機連線端口（探測順序）：已記錄端口之後逐一嘗試
_CANDIDATE_PORTS = [7897, 7890, 10808, 10809, 17890]


def _win_system_proxy() -> tuple[str, int] | None:
    """讀 Windows 已記錄的連線端口（註冊表），返回 (addr, port) 或 None。

    注意：本機網絡工具常把端口寫入 ProxyServer，但 ProxyEnable 開關可能因
    重啟而未同步（=0），且端口會變、註冊表值可能過期——
    所以取到後仍要探測存活（見 resolve_proxy）。
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        finally:
            winreg.CloseKey(key)
    except OSError:
        return None
    if not server:
        return None
    return _parse_proxy_server(str(server))


def _probe_proxy(addr: str, port: int, timeout: float = 0.6) -> bool:
    """TCP 探測代理端口是否存活。"""
    try:
        s = socket.create_connection((addr, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _parse_proxy_server(server: str) -> tuple[str, int] | None:
    """解析 ProxyServer，支持兩種格式：

    - 單一無協議：`127.0.0.1:7897`
    - 多協議：`http=127.0.0.1:7897;https=127.0.0.1:7897;socks=127.0.0.1:7897`

    優先返回 socks，其次 http，最後無協議前綴的單一地址。
    """
    parts = [p.strip() for p in server.split(";") if p.strip()]
    by_scheme: dict[str, tuple[str, int]] = {}
    for p in parts:
        if "=" in p:
            scheme, value = p.split("=", 1)
            parsed = _split_host_port(value)
            if parsed:
                by_scheme[scheme.strip().lower()] = parsed
        else:
            parsed = _split_host_port(p)
            if parsed:
                by_scheme[""] = parsed
    for scheme in ("socks", "socks5", "http", "https", ""):
        if scheme in by_scheme:
            return by_scheme[scheme]
    return None


def _split_host_port(value: str) -> tuple[str, int] | None:
    value = value.strip()
    if not value:
        return None
    if "://" in value:
        value = value.split("://", 1)[1]
    host, _, port = value.rpartition(":")
    if not host or not port:
        return None
    try:
        return host.strip("[] "), int(port)
    except ValueError:
        return None


def resolve_proxy(
    cfg_proxy: dict | None, default_type: str = "socks5"
) -> tuple[str, str, int] | None:
    """解析代理，返回 (type, addr, port) 或 None（直連）。

    優先級：
      1. config 顯式 enabled=true → 信任使用者設定（不探測）
      2. 探測式自動適配：註冊表已記錄的端口 → 可用即用；
         不可用則掃常見端口（_CANDIDATE_PORTS）——端口變化自動跟上
      3. 全都不可用 → None（直連）

    default_type：註冊表不攜帶協議類型，故由調用方指定——
    TG 長連線建議 socks5（python_socks 已裝），Bybit ccxt 短連線建議 http。
    """
    if cfg_proxy and cfg_proxy.get("enabled"):
        ptype = str(cfg_proxy.get("type", default_type)).lower()
        if ptype not in ("socks5", "socks4", "http"):
            raise ValueError(f"不支持的代理類型：{ptype}（socks5 | http）")
        return (
            ptype,
            str(cfg_proxy.get("addr", "127.0.0.1")),
            int(cfg_proxy.get("port", 7890)),
        )
    candidates: list[tuple[str, int]] = []
    sys_proxy = _win_system_proxy()
    if sys_proxy:
        candidates.append(sys_proxy)
    for p in _CANDIDATE_PORTS:
        c = ("127.0.0.1", p)
        if c not in candidates:
            candidates.append(c)
    for addr, port in candidates:
        if _probe_proxy(addr, port):
            # 故意不打日誌：本機網絡連線細節不得出現在使用者可見視窗/問題報告
            return (default_type, addr, port)
    return None
