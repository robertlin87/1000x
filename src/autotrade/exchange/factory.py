"""適配器工廠：按設定構造交易所適配器。"""
from __future__ import annotations

from .base import ExchangeAdapter
from .binance import BinanceAdapter
from .bitget import BitgetAdapter
from .bitunix_rest import BitunixRestAdapter
from .bybit import BybitAdapter
from .deepcoin import DeepcoinAdapter
from .gate import GateAdapter


def get_adapter(exchange_name: str, api_config: dict,
                proxy: dict | None = None) -> ExchangeAdapter:
    """按交易所名構造適配器。api_config 為 config.yaml exchanges.<name> 段。"""
    name = str(exchange_name).lower()
    if name == "bybit":
        return BybitAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            testnet=bool(api_config.get("testnet", False)),
            proxy=proxy,
        )
    if name == "binance":
        return BinanceAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            proxy=proxy,
        )
    if name == "bitget":
        return BitgetAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            passphrase=api_config.get("passphrase", ""),
            proxy=proxy,
        )
    if name == "gate":
        return GateAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            proxy=proxy,
        )
    if name == "deepcoin":
        return DeepcoinAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            passphrase=api_config.get("passphrase", ""),
            proxy=proxy,
        )
    if name == "bitunix":
        return BitunixRestAdapter(
            api_key=api_config.get("apiKey", ""),
            secret=api_config.get("secret", ""),
            proxy=proxy,
        )
    raise NotImplementedError(f"交易所適配器尚未實現：{exchange_name}")
