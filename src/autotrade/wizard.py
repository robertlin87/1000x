"""引导式配置：调用 GUI 配置向导（首次配置用）。"""
from __future__ import annotations


def run_wizard() -> None:
    """打开 GUI 配置向导，交互式生成 config 并自检连通性。"""
    from .gui.wizard import Wizard

    Wizard().run()
