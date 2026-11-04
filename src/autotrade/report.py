"""问题报告生成：扫描 temp 日志，聚合去重错误 + 密钥脱敏，导出 txt。

用户规则（2026-11-04）：
- 原始日志不去重（每次发生都记录）；去重发生在报告层——同一错误
  聚合为一行带次数，粉丝贴给你的报告不会是大段重复
- 报告是一次性快照，写入 temp 目录，粉丝把 txt 发给你即可
"""
from __future__ import annotations

import logging
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

from . import paths
from .constants import VERSION

log = logging.getLogger("autotrade.report")

_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<level>\w+) (?P<name>\S+): (?P<msg>.*)$"
)


def _secret_values() -> list[str]:
    """从配置收集需要脱敏的值（apiKey/secret/passphrase/api_hash）。"""
    values: list[str] = []
    try:
        from .config import load_config
        cfg = load_config(str(paths.config_path()))
    except Exception:
        return values
    tg = cfg.telegram or {}
    if tg.get("api_hash"):
        values.append(str(tg["api_hash"]))
    ex = cfg.exchanges or {}
    for name in ("bybit", "binance", "bitget", "gate", "deepcoin", "bitunix"):
        for k in ("apiKey", "secret", "passphrase"):
            v = (ex.get(name) or {}).get(k)
            if v:
                values.append(str(v))
    return values


def _scrub(text: str, values: list[str]) -> str:
    for v in values:
        if v:
            text = text.replace(v, "***")
    return text


def _log_files() -> list[Path]:
    d = paths.temp_dir()
    if not d.exists():
        return []
    return sorted(d.glob("autotrade.log*"))


def _iter_log_lines():
    """遍历全部日志文件，产出 (ts, level, name, msg, raw)。"""
    for f in _log_files():
        try:
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _LOG_LINE_RE.match(raw)
                if m:
                    yield m.group("ts"), m.group("level"), m.group("name"), m.group("msg"), raw
        except OSError:
            continue


def _error_summary(lines) -> str:
    """错误摘要：按签名（logger + 消息前 80 字符）聚合去重，按次数排序。"""
    groups: dict[str, dict] = {}
    for ts, level, name, msg, _raw in lines:
        if level not in ("ERROR", "CRITICAL", "WARNING"):
            continue
        sig = f"{name}|{msg[:80]}"
        g = groups.setdefault(sig, {
            "count": 0, "first": ts, "last": ts, "level": level, "msg": msg,
        })
        g["count"] += 1
        g["first"] = min(g["first"], ts)
        g["last"] = max(g["last"], ts)
    items = sorted(groups.values(), key=lambda g: -g["count"])
    out = []
    for g in items[:20]:
        out.append(f"[发生 {g['count']} 次] {g['first']} ~ {g['last']} {g['level']}: {g['msg'][:200]}")
    return "\n".join(out) if out else "（无 ERROR/WARNING 记录）"


def collect_report() -> str:
    """生成报告全文（含脱敏）。"""
    lines = list(_iter_log_lines())
    exchange = ""
    try:
        from .config import load_config
        cfg = load_config(str(paths.config_path()))
        exchange = str((cfg.exchanges or {}).get("active", ""))
    except Exception:
        pass
    head = (
        "加密林教头VIP跟单助手 问题报告\n"
        f"版本: {VERSION} | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"系统: {platform.system()} {platform.release()} | Python {sys.version.split()[0]}\n"
        f"交易所: {exchange or '未配置'}\n"
        f"{'=' * 60}\n"
    )
    body = "【错误摘要（去重聚合）】\n" + _error_summary(lines) + "\n"
    tail = "\n【最近日志（上下文）】\n" + "\n".join(r for *_x, r in lines[-100:])
    return _scrub(head + body + tail, _secret_values())


def write_report_file() -> Path:
    """生成报告写入 temp 目录，返回文件路径。"""
    paths.ensure_dirs()
    path = paths.temp_dir() / f"autotrade-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(collect_report(), encoding="utf-8")
    log.info("问题报告已生成：%s", path)
    return path
