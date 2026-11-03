"""Deepcoin 适配器：需实测精度、合约倍数与部分成交后的挂单行为。"""
from __future__ import annotations

from .base import ExchangeAdapter


class DeepcoinAdapter(ExchangeAdapter):
    """TODO M4：ccxt.deepcoin 封装，paper 全路径验证后方可实盘。"""

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": False}
