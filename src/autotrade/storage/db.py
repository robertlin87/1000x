"""SQLite 持久化。

- signals：报单，去重键 UNIQUE(chat_id, order_id)；编辑事件 upsert 更新 raw_text
- signal_ops：统一事件层，编辑行与新消息通知都进此层，UNIQUE(chat_id, order_id, line_hash)
  幂等——仅新增事件触发动作
- orders / positions / events：订单、持仓（tp_hit_count、remaining_qty）、审计
"""
from __future__ import annotations

import json

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    order_id TEXT NOT NULL,
    analyst TEXT, symbol TEXT, side TEXT, entry REAL, is_limit INTEGER DEFAULT 0,
    leverage INTEGER, sl REAL, tps_json TEXT, margin_pct REAL, risk_pct REAL,
    stop_dist_pct REAL, raw_text TEXT, status TEXT DEFAULT 'new',
    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(chat_id, order_id)
);

CREATE TABLE IF NOT EXISTS signal_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    order_id TEXT NOT NULL,
    line_hash TEXT NOT NULL,
    line_text TEXT NOT NULL,
    source TEXT NOT NULL,              -- edit | notice
    action_type TEXT NOT NULL,         -- tp_hit|all_tp|move_sl|hedge|hedge_exit|close|ignore|unknown
    tp_index INTEGER, price REAL, ts_text TEXT,
    processed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(chat_id, order_id, line_hash)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_row_id INTEGER REFERENCES signals(id),
    exchange TEXT, order_id TEXT, symbol TEXT, side TEXT, order_type TEXT,
    qty REAL, price REAL, sl_price REAL, tp_prices_json TEXT, leverage INTEGER,
    status TEXT, filled_qty REAL DEFAULT 0, avg_price REAL,
    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_row_id INTEGER REFERENCES signals(id),
    exchange TEXT, symbol TEXT, side TEXT, qty REAL, avg_entry REAL,
    sl_price REAL, tp_hit_count INTEGER DEFAULT 0, remaining_qty REAL,
    state TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions(id),
    type TEXT NOT NULL,                -- fill|amend|error|reconcile
    payload_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(SCHEMA)
    await db.commit()
    return db


async def upsert_signal(db: aiosqlite.Connection, chat_id: int, signal) -> bool:
    """插入报单；编辑事件按 (chat_id, order_id) upsert，仅刷新 raw_text。

    返回 True=新报单，False=已知报单（编辑更新）。
    注意：ON CONFLICT DO UPDATE 的 rowcount 对插入和更新都算 1，
    所以用 INSERT OR IGNORE 的 rowcount（忽略时=0）区分新旧。
    """
    cur = await db.execute(
        """INSERT OR IGNORE INTO signals
           (chat_id, order_id, analyst, symbol, side, entry, is_limit,
            leverage, sl, tps_json, margin_pct, risk_pct, stop_dist_pct, raw_text, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new')""",
        (
            chat_id, signal.order_id, signal.analyst, signal.symbol, signal.side,
            signal.entry, int(signal.is_limit), signal.leverage, signal.sl,
            json.dumps(signal.tps), signal.margin_pct, signal.risk_pct,
            signal.stop_dist_pct, signal.raw_text,
        ),
    )
    if cur.rowcount == 1:
        await db.commit()
        return True
    await db.execute(
        "UPDATE signals SET raw_text=?, updated_at=datetime('now') "
        "WHERE chat_id=? AND order_id=?",
        (signal.raw_text, chat_id, signal.order_id),
    )
    await db.commit()
    return False


async def add_signal_op(
    db: aiosqlite.Connection,
    chat_id: int,
    order_id: str,
    line_hash: str,
    line_text: str,
    source: str,
    action_type: str,
    tp_index: int | None = None,
    price: float | None = None,
    ts_text: str = "",
) -> bool:
    """写入统一事件层。返回 True=新事件（需触发动作），False=重复（幂等忽略）。

    UNIQUE(chat_id, order_id, line_hash) + INSERT OR IGNORE：编辑行与新消息
    通知的同一操作只算一次。
    """
    cur = await db.execute(
        """INSERT OR IGNORE INTO signal_ops
           (chat_id, order_id, line_hash, line_text, source, action_type,
            tp_index, price, ts_text)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (chat_id, order_id, line_hash, line_text, source, action_type,
         tp_index, price, ts_text),
    )
    await db.commit()
    return cur.rowcount == 1


async def get_signal(db: aiosqlite.Connection, chat_id: int, order_id: str):
    """取报单（供訂單修改 diff 旧值）。无记录返回 None。

    返回 types.SimpleNamespace，含 symbol/side/entry/sl/tps。
    """
    from types import SimpleNamespace

    cur = await db.execute(
        "SELECT symbol, side, entry, sl, tps_json FROM signals "
        "WHERE chat_id=? AND order_id=?",
        (chat_id, order_id),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return SimpleNamespace(
        symbol=row[0], side=row[1], entry=row[2], sl=row[3],
        tps=json.loads(row[4] or "[]"),
    )


async def update_signal_fields(
    db: aiosqlite.Connection,
    chat_id: int,
    order_id: str,
    tps: list[float],
    sl: float,
    entry: float,
) -> None:
    """訂單修改后同步 signals 表的 tps/sl/entry（后续修改以此为旧值）。"""
    await db.execute(
        "UPDATE signals SET tps_json=?, sl=?, entry=?, updated_at=datetime('now') "
        "WHERE chat_id=? AND order_id=?",
        (json.dumps(tps), sl, entry, chat_id, order_id),
    )
    await db.commit()
