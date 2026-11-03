"""适配器工厂：按配置构造交易所适配器。"""
from __future__ import annotations

from .base import ExchangeAdapter
from .bybit import BybitAdapter


def get_adapter(exchange_name: str, api_config: dict, proxy: dict | None = None) -> ExchangeAdapter:
    """按交易所名构造适配器。

    MVP 仅 Bybit；M4 起接入 Bitget / Deepcoin / Bitunix。
    Bitunix 先探测 ccxt.bitunix，存在用薄封装，不存在走手写 REST。
    """
    name = str(exchange_name).lower()
    if name == "bybit":
        return BybitAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            testnet=bool(api_config.get("testnet", False)),
            proxy=proxy,
        )
    raise NotImplementedError(f"交易所适配器尚未实现：{exchange_name}")
