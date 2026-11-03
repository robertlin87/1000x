"""Bitget 适配器：passphrase 必填；TP/SL 独立挂载（attach_sl_tp）。"""
from __future__ import annotations

from .base import ExchangeAdapter


class BitgetAdapter(ExchangeAdapter):
    """TODO M4：ccxt.bitget 封装。"""

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": False}
