"""应用入口：首次运行进配置向导，已配置则直接启动监听窗口。"""
from __future__ import annotations

from . import paths
from .gui.runner import RunnerWindow
from .gui.wizard import Wizard


def main() -> None:
    paths.ensure_dirs()
    if not paths.config_path().exists():
        wizard = Wizard()
        wizard.run()
        if not wizard.saved:
            return  # 用户取消配置
    RunnerWindow().run()


if __name__ == "__main__":
    main()
