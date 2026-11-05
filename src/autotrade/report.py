"""問題報告生成：掃描 temp 日誌，聚合去重錯誤 + 密鑰脫敏，導出 txt。

使用者規則（2026-11-04）：
- 原始日誌不去重（每次發生都記錄）；去重發生在報告層——同一錯誤
  聚合為一行帶次數，粉絲貼給你的報告不會是大段重複
- 報告是一次性快照，寫入 temp 目錄，粉絲把 txt 發給你即可
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
from .logfile import scrub_network_words

log = logging.getLogger("autotrade.report")

_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<level>\w+) (?P<name>\S+): (?P<msg>.*)$"
)


def _secret_values() -> list[str]:
    """從設定收集需要脫敏的值（apiKey/secret/passphrase/api_hash）。"""
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
    """遍歷全部日誌檔案，產出 (ts, level, name, msg, raw)。"""
    for f in _log_files():
        try:
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _LOG_LINE_RE.match(raw)
                if m:
                    yield m.group("ts"), m.group("level"), m.group("name"), m.group("msg"), raw
        except OSError:
            continue


def _error_summary(lines) -> str:
    """錯誤摘要：按簽名（logger + 消息前 80 字符）聚合去重，按次數排序。"""
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
        out.append(f"[發生 {g['count']} 次] {g['first']} ~ {g['last']} {g['level']}: {g['msg'][:200]}")
    return "\n".join(out) if out else "（無 ERROR/WARNING 記錄）"


def collect_report() -> str:
    """生成報告全文（含脫敏）。"""
    lines = list(_iter_log_lines())
    exchange = ""
    try:
        from .config import load_config
        cfg = load_config(str(paths.config_path()))
        exchange = str((cfg.exchanges or {}).get("active", ""))
    except Exception:
        pass
    head = (
        "加密林教頭VIP跟單助手 問題報告\n"
        f"版本: {VERSION} | 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"系統: {platform.system()} {platform.release()} | Python {sys.version.split()[0]}\n"
        f"交易所: {exchange or '未設定'}\n"
        f"{'=' * 60}\n"
    )
    body = "【錯誤摘要（去重聚合）】\n" + _error_summary(lines) + "\n"
    tail = "\n【最近日誌（上下文）】\n" + "\n".join(r for *_x, r in lines[-100:])
    # 歷史日誌（本次改動前寫入的）也可能含本機網絡連線細節，導出前統一清洗
    return scrub_network_words(_scrub(head + body + tail, _secret_values()))


def write_report_file() -> Path:
    """生成報告寫入 temp 目錄，返回檔案路徑。"""
    paths.ensure_dirs()
    path = paths.temp_dir() / f"autotrade-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(collect_report(), encoding="utf-8")
    log.info("問題報告已生成：%s", path)
    return path
