"""引導式設定：調用 GUI 設定向導（首次設定用）。"""
from __future__ import annotations


def run_wizard() -> None:
    """打開 GUI 設定向導，交互式生成 config 並自檢連通性。"""
    from .gui.wizard import Wizard

    Wizard().run()
