"""生成问题报告：python scripts/report.py

输出 temp 目录下的 txt 文件（聚合去重后的错误摘要 + 最近日志上下文）。
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
    print("问题报告已生成：", path)
    print("把这个文件发给你对接的人即可。")


if __name__ == "__main__":
    main()
