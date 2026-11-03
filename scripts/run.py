"""启动入口：python scripts/run.py --config config/config.yaml"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autotrade.main import run  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)  # 屏蔽其他群的同步噪音日志


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram 信号自动跟单机器人")
    parser.add_argument("--config", default=None, help="配置文件路径（缺省用外部目录的 config.yaml）")
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
