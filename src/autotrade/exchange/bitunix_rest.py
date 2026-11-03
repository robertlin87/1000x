"""Bitunix 适配器（手写 REST 兜底）：ccxt 不支持时实现同一 ExchangeAdapter 接口。"""
from __future__ import annotations

from .base import ExchangeAdapter


class BitunixRestAdapter(ExchangeAdapter):
    """TODO M4：手写 REST（HMAC-SHA256 签名），接进同一引擎。"""

    @property
    def capabilities(self) -> dict:
        return {"supports_attached_sl": False}
