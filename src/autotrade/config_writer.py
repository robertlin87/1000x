"""設定生成與寫回的唯一實現（CLI 嚮導與 GUI 嚮導共用）。

修復 GUI 舊實現 _write_config 的兩處缺陷：
  - 交易所模板用 passphrase 而非 password 死鍵；
  - storage.db_path 不寫空串（寫 data/autotrade.db，絕不落到目前目錄）。

同時承載 friendly_selfcheck_error（從 gui/wizard.py 遷移過來，避免 CLI 引入 tkinter 依賴）。
"""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from . import paths
from .exchange.schemas import EXCHANGE_ORDER, EXCHANGE_SCHEMAS

SESSION_NAME = "autotrade_session"


def friendly_selfcheck_error(prefix: str, exc: Exception) -> str:
    """把常見底層異常翻成使用者能自己動手解決的中文提示（不甩原始堆棧）。"""
    msg = str(exc)
    low = msg.lower()
    if "database is locked" in low:
        return (
            f"{prefix}：Telegram 會話檔案正被佔用（database is locked）。\n"
            "  → 請先關閉其他正在運行的「加密林教頭VIP跟單助手」視窗/監聽程序，"
            "只保留一個，再重新打開本軟件；仍不行就重啟電腦後重試。\n"
            "  （同一個 TG 會話不能被兩個程序同時使用）"
        )
    if "10002" in msg or "server timestamp" in low or "recv_window" in low:
        return (
            f"{prefix}：電腦時間不準，交易所拒絕了請求（時間戳超出接收視窗）。\n"
            "  → Windows「設定 → 時間和語言 → 日期和時間」打開「自動設定時間」，"
            "點「立即同步」，然後重試。\n"
            f"  （原始信息：{msg[:160]}）"
        )
    return f"{prefix}：{msg}"


def _template() -> dict:
    """以 config.example.yaml 為基底（保留註釋與完整結構），返回可被覆蓋的 dict。"""
    tmpl = paths.app_dir() / "config" / "config.example.yaml"
    if tmpl.exists():
        with open(tmpl, encoding="utf-8") as f:
            data = YAML().load(f) or {}
        return data
    # 極端情況模板缺失時的兜底最小結構
    return {
        "telegram": {
            "session_name": SESSION_NAME,
            "api_id": 0,
            "api_hash": "",
            "proxy": {"enabled": False, "type": "socks5", "addr": "127.0.0.1", "port": 7890},
        },
        "dry_run": False,
        "exchanges": {
            "active": "bybit",
            "proxy": {"enabled": False, "type": "http", "addr": "127.0.0.1", "port": 7897},
        },
        "risk": {"order_multiplier": 1.0},
        "analysts": {"allow_all": True, "list": []},
        "behavior": {
            "amend_sl_on_move": True,
            "close_on_manual_close": True,
            "cancel_symbol_orders_on_terminal": True,
        },
        "notify": {"send_to": ""},
        "storage": {"db_path": "data/autotrade.db"},
    }


def blank_exchange_fields(active: str, credentials: dict) -> dict:
    """生成 exchanges 下六家交易所段：僅 active 一家填入 credentials，其餘留空。

    欄位鍵名嚴格按 EXCHANGE_SCHEMAS（含 passphrase 僅 bitget/deepcoin），不寫 password 死鍵。
    """
    out: dict = {}
    for name in EXCHANGE_ORDER:
        fields = {f["key"]: "" for f in EXCHANGE_SCHEMAS[name]["fields"]}
        if name == active:
            for k, v in credentials.items():
                if k in fields:
                    fields[k] = v
        out[name] = fields
    return out


def build_config(
    *,
    api_id: int,
    api_hash: str,
    exchange: str,
    credentials: dict,
    order_multiplier: float,
    base: dict | None = None,
) -> dict:
    """組裝與 config.example.yaml 對齊的完整設定 dict（供 write_config 落盤）。

    base 省略時以 config.example.yaml 為模板；傳入 base 可避免重複讀模板（如 GUI 複用）。
    """
    cfg = base if base is not None else _template()

    tg = cfg.setdefault("telegram", {})
    tg["session_name"] = SESSION_NAME
    tg["api_id"] = int(api_id)
    tg["api_hash"] = str(api_hash)

    # 面向真實使用者：始終真實下單
    cfg["dry_run"] = False

    ex = cfg.setdefault("exchanges", {})
    ex["active"] = exchange
    if not ex.get("proxy"):
        ex["proxy"] = {"enabled": False, "type": "http", "addr": "127.0.0.1", "port": 7897}
    for name in EXCHANGE_ORDER:
        ex[name] = blank_exchange_fields(exchange, credentials)[name]

    risk = cfg.setdefault("risk", {})
    risk["order_multiplier"] = float(order_multiplier)

    storage = cfg.setdefault("storage", {})
    storage["db_path"] = "data/autotrade.db"

    return cfg


def write_config(path: str | Path, cfg: dict) -> None:
    """把設定寫回 path。

    - path 不存在：直接寫 cfg（保留 ruamel 註釋）。
    - path 已存在：頂層 dict 做一層合併（保留未改欄位/註釋），再寫回。
    """
    path = Path(path)
    yaml = YAML()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing = yaml.load(f) or {}
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(existing.get(k), dict):
                merged = dict(existing[k])
                merged.update(v)
                existing[k] = merged
            else:
                existing[k] = v
        data = existing
    else:
        data = cfg
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
