"""JSONL 回放（M1 验收工具）：把 listen.py 采集的消息喂给解析管线，dry-run 验证。

用法：
  python scripts/listen.py                     # 先采集真实消息到 data/messages.jsonl
  python scripts/replay.py --input data/messages.jsonl

默认写入 data/replay.db（不污染正式库）；--db 可指定。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autotrade.config import load_config  # noqa: E402
from autotrade.main import MessagePipeline  # noqa: E402
from autotrade.notify.notifier import Notifier  # noqa: E402
from autotrade.signal_source.base import RawMessage  # noqa: E402
from autotrade.storage.db import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("replay")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main() -> None:
    parser = argparse.ArgumentParser(description="JSONL 消息回放（dry-run）")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--input", default="data/messages.jsonl", help="listen.py 采集的 JSONL")
    parser.add_argument("--db", default="data/replay.db", help="回放库路径（默认 data/replay.db）")
    args = parser.parse_args()

    cfg = load_config(args.config)
    src = Path(args.input)
    if not src.exists():
        log.error("输入文件不存在：%s（先跑 python scripts/listen.py 采集）", src)
        return

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await init_db(str(db_path))
    pipeline = MessagePipeline(db, Notifier(dry_run=True))

    count = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        raw = RawMessage(
            chat_id=d.get("chat_id", 0),
            chat_title=d.get("chat_title", ""),
            sender_id=d.get("sender_id"),
            msg_id=d.get("msg_id", 0),
            text=d.get("text", ""),
            ts=d.get("ts", ""),
            is_edit=bool(d.get("is_edit")),
        )
        await pipeline.handle(raw)
        count += 1
    log.info("回放完成：%s 条消息（事件库 %s）", count, db_path)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
