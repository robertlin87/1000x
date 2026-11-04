"""应用入口：首次运行进配置向导，已配置则直接启动监听窗口。"""
from __future__ import annotations

from . import paths
from .gui.runner import RunnerWindow
from .gui.wizard import Wizard


def _install_crash_hooks() -> None:
    """未捕获异常落盘：GUI 直接崩溃也能在 temp 日志里留下现场。"""
    import logging
    import sys
    import threading

    from .logfile import install_file_logging

    install_file_logging()
    logger = logging.getLogger("autotrade.crash")

    def _hook(exc_type, exc_value, exc_tb):
        logger.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args):
        logger.critical("线程未捕获异常",
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def main() -> None:
    paths.ensure_dirs()
    _install_crash_hooks()
    if not paths.config_path().exists():
        wizard = Wizard()
        wizard.run()
        if not wizard.saved:
            return  # 用户取消配置
    RunnerWindow().run()


if __name__ == "__main__":
    main()
