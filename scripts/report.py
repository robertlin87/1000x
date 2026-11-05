"""生成問題報告：python scripts/report.py

輸出 temp 目錄下的 txt 檔案（聚合去重後的錯誤摘要 + 最近日誌上下文）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autotrade import paths  # noqa: E402
from autotrade.report import write_report_file  # noqa: E402


def main() -> None:
    paths.ensure_dirs()
    path = write_report_file()
    print("問題報告已生成：", path)
    print("把這個檔案發給你對接的人即可。")


if __name__ == "__main__":
    main()
