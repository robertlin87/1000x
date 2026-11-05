"""啟動入口：python scripts/run.py --config config/config.yaml"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autotrade import paths  # noqa: E402
from autotrade.cli_setup import (  # noqa: E402
    prompt_startup_menu,
    run_first_time_setup,
)
from autotrade.main import run  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)  # 屏蔽其他群的同步噪音日誌

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram 信號自動跟單機器人")
    parser.add_argument("--config", default=None, help="設定檔案路徑（缺省用外部目錄的 config.yaml）")
    args = parser.parse_args()
    config_path = args.config or str(paths.config_path())
    if not Path(config_path).exists():
        run_first_time_setup(config_path)
    else:
        prompt_startup_menu(config_path)
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
