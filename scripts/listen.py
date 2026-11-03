"""监听验证脚本（M1 第一步）：把群消息输出为 JSONL，作为下一步交易管线的输入。

用法（在项目根目录 E:\\VibeCoding 的终端里跑）：
  1) 首次登录（交互式：输入手机号 + 验证码）：
     python scripts/listen.py --login
  2) 列出最近的群会话，确认信号群的准确名字：
     python scripts/listen.py --list
  3) 开始监听（消息打印到屏幕，同时追加写入 data/messages.jsonl）：
     python scripts/listen.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autotrade.config import load_config  # noqa: E402
from autotrade.signal_source.base import RawMessage  # noqa: E402
from autotrade.signal_source.telegram_userbot import TelegramUserbotSource  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)  # 屏蔽其他群的同步噪音日志
log = logging.getLogger("listen")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def record(raw: RawMessage, output: str) -> None:
    """输出变量：JSONL 落盘（下游交易管线从这里读）+ 屏幕打印。"""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(raw), ensure_ascii=False) + "\n")
    tag = "✏️编辑" if raw.is_edit else "🆕新消息"
    print(f"[{tag}] [{raw.chat_title}] (msg_id={raw.msg_id}) {raw.text[:100]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="TG 信号群监听")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--login", action="store_true", help="仅登录并保存会话后退出")
    parser.add_argument("--list", action="store_true", help="列出最近 50 个群/频道后退出")
    parser.add_argument("--output", default="data/messages.jsonl", help="消息输出文件")
    args = parser.parse_args()

    cfg = load_config(args.config)
    tg = cfg.telegram
    source = TelegramUserbotSource(
        handler=lambda raw: record(raw, args.output),
        api_id=int(tg.get("api_id", 0)),
        api_hash=tg.get("api_hash", ""),
        session_name=tg.get("session_name", "autotrade_session"),
        chat_title=tg.get("chat_title") or None,
        chat_id=tg.get("chat_id") or None,
        proxy=tg.get("proxy"),
    )

    if args.login:
        await source.login()
        print("✅ 登录完成。下一步：python scripts/listen.py --list 找到信号群名")
        return

    if args.list:
        for name, chat_id in await source.list_dialogs():
            print(f"{name}\t{chat_id}")
        return

    await source.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出监听")
