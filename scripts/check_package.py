"""原始碼分發前只讀自檢：列出絕不可隨包發出的敏感/構建檔案。

無副作用，僅打印檢查結論。用法：python scripts/check_package.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 絕不能出現在發給使用者的原始碼包裡的東西
FORBIDDEN = [
    "config/config.yaml",            # 含真實 api_id/api_hash 與交易所 Key
    "autotrade_session.session",
    "autotrade_session.session-journal",
    "data/",
    "temp/",
    "logs/",
    ".venv/",
    "dist/",
    "build/",
    ".git/",
    ".codebuddy/",
]

# 使用者拿到後運行必需存在的檔案
REQUIRED = [
    "src/autotrade/",
    "scripts/run.py",
    "install.bat",
    "start_run.bat",
    "config/config.example.yaml",
    "pyproject.toml",
]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    forbidden_found = [rel for rel in FORBIDDEN if (root / rel).exists()]
    required_missing = [rel for rel in REQUIRED if not (root / rel).exists()]

    print("=" * 50)
    print("  原始碼分發自檢")
    print("=" * 50)
    if forbidden_found:
        print("發現以下禁止外發的檔案/目錄，打包前請刪除：")
        for rel in forbidden_found:
            print(f"  禁止外發：{rel}")
    else:
        print("  OK：未發現禁止外發的敏感/構建檔案。")
    if required_missing:
        print("以下運行必需的檔案缺失：")
        for rel in required_missing:
            print(f"  缺失：{rel}")
    else:
        print("  OK：運行必需檔案齊全。")

    if forbidden_found or required_missing:
        print("\n結論：目前目錄不適合直接打包分發，請先處理上述問題。")
        return 1
    print("\n結論：可以用於原始碼分發。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
