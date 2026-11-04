"""代理动态解析：优先 config 显式配置，否则自动检测系统代理，否则直连。

解决「代理端口写死」问题：用户 VPN 重启后系统代理端口会变，写死端口会导致连不上。
自动检测采用**探测式**：注册表里的系统代理先探测端口存活，死了再扫常见
VPN 端口（Clash/v2rayN 等），找到活端口才使用——VPN 换端口自动跟上，零配置。
"""
from __future__ import annotations

import logging
import socket

log = logging.getLogger("autotrade.proxy")

# 常见本地代理端口（探测顺序）：注册表值之后逐一尝试
_CANDIDATE_PORTS = [7897, 7890, 10808, 10809, 17890]


def _win_system_proxy() -> tuple[str, int] | None:
    """读 Windows 系统代理（注册表），返回 (addr, port) 或 None。

    注意：VPN 客户端常把代理端口写入 ProxyServer，但 ProxyEnable 开关可能因
    重启而未同步（=0），且 VPN 重启后端口会变、注册表值可能过期——
    所以取到后仍要探测存活（见 resolve_proxy）。
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
    """TCP 探测代理端口是否存活。"""
    try:
        s = socket.create_connection((addr, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _parse_proxy_server(server: str) -> tuple[str, int] | None:
    """解析 ProxyServer，支持两种格式：

    - 单一无协议：`127.0.0.1:7897`
    - 多协议：`http=127.0.0.1:7897;https=127.0.0.1:7897;socks=127.0.0.1:7897`

    优先返回 socks，其次 http，最后无协议前缀的单一地址。
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
    """解析代理，返回 (type, addr, port) 或 None（直连）。

    优先级：
      1. config 显式 enabled=true → 信任用户配置（不探测）
      2. 探测式自动检测：注册表系统代理端口 → 存活即用；
         死了则扫常见 VPN 端口（_CANDIDATE_PORTS）——VPN 重启换端口自动跟上
      3. 全都不活 → None（直连）

    default_type：系统代理不携带协议类型，故由调用方指定——
    TG 长连接建议 socks5（python_socks 已装），Bybit ccxt 短连接建议 http。
    """
    if cfg_proxy and cfg_proxy.get("enabled"):
        ptype = str(cfg_proxy.get("type", default_type)).lower()
        if ptype not in ("socks5", "socks4", "http"):
            raise ValueError(f"不支持的代理类型：{ptype}（socks5 | http）")
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
            log.info("检测到存活代理：%s:%s", addr, port)
            return (default_type, addr, port)
    log.info("未检测到存活代理，直连")
    return None
