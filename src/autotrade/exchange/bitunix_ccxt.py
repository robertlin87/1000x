"""Bitunix 适配器（ccxt 路径）：优先探测 ccxt 是否支持 bitunix。"""
from __future__ import annotations

from .base import ExchangeAdapter


class BitunixCcxtAdapter(ExchangeAdapter):
    """TODO M4：探测 ccxt.bitunix 存在则薄封装；不存在走 bitunix_rest。"""

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": False}
