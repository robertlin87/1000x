"""多交易所接入单测：schema 完整性、工厂分发、非 attached 进场分支。"""
import unittest

from autotrade.exchange.binance import BinanceAdapter
from autotrade.exchange.bitget import BitgetAdapter
from autotrade.exchange.bitunix_rest import BitunixRestAdapter
from autotrade.exchange.bybit import BybitAdapter
from autotrade.exchange.deepcoin import DeepcoinAdapter
from autotrade.exchange.factory import get_adapter
from autotrade.exchange.gate import GateAdapter
from autotrade.exchange.schemas import EXCHANGE_ORDER, EXCHANGE_SCHEMAS


class TestSchemas(unittest.TestCase):
    def test_all_exchanges_present(self):
        self.assertEqual(sorted(EXCHANGE_SCHEMAS), sorted(EXCHANGE_ORDER))
        self.assertEqual(len(EXCHANGE_SCHEMAS), 6)

    def test_fields_complete(self):
        for name, schema in EXCHANGE_SCHEMAS.items():
            keys = [f["key"] for f in schema["fields"]]
            self.assertIn("apiKey", keys, name)
            self.assertIn("secret", keys, name)
            self.assertGreaterEqual(len(schema["notes"]), 2, name)
            self.assertTrue(schema["label"], name)

    def test_passphrase_required_only_where_needed(self):
        self.assertIn("passphrase", [f["key"] for f in EXCHANGE_SCHEMAS["bitget"]["fields"]])
        self.assertIn("passphrase", [f["key"] for f in EXCHANGE_SCHEMAS["deepcoin"]["fields"]])
        for name in ("bybit", "binance", "gate", "bitunix"):
            self.assertNotIn("passphrase", [f["key"] for f in EXCHANGE_SCHEMAS[name]["fields"]])


class TestFactory(unittest.TestCase):
    def test_dispatch(self):
        cfg = {"apiKey": "k", "secret": "s", "passphrase": "p"}
        self.assertIsInstance(get_adapter("bybit", cfg), BybitAdapter)
        self.assertIsInstance(get_adapter("binance", cfg), BinanceAdapter)
        self.assertIsInstance(get_adapter("bitget", cfg), BitgetAdapter)
        self.assertIsInstance(get_adapter("gate", cfg), GateAdapter)
        self.assertIsInstance(get_adapter("deepcoin", cfg), DeepcoinAdapter)
        self.assertIsInstance(get_adapter("bitunix", cfg), BitunixRestAdapter)

    def test_passphrase_required(self):
        with self.assertRaises(ValueError):
            BitgetAdapter("k", "s", "")
        with self.assertRaises(ValueError):
            DeepcoinAdapter("k", "s", "")
        # 不需要 passphrase 的所不报错
        GateAdapter("k", "s")
        BinanceAdapter("k", "s")

    def test_unknown_exchange(self):
        with self.assertRaises(NotImplementedError):
            get_adapter("kraken", {})


class TestNonAttachedEnter(unittest.IsolatedAsyncioTestCase):
    """非 attached 交易所：进场走独立 SL 挂单分支。"""

    async def test_attach_sl_called_after_entry(self):
        from tests.test_execution import StubAdapter  # 复用可控假适配器
        from autotrade.execution.order_manager import OrderManager
        from autotrade.parser.entry_parser import Signal

        class NonAttachedStub(StubAdapter):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.attached_sl: list = []

            @property
            def capabilities(self):
                return {"supports_attached_sl": False}

            async def attach_sl_tp(self, order_id, symbol, sl, tps):
                self.attached_sl.append((symbol, sl))

            async def fetch_position(self, symbol):
                return {"symbol": symbol, "side": "long", "qty": 100.0}

        adapter = NonAttachedStub()
        om = OrderManager(adapter)
        sig = Signal(order_id="1", symbol="LITUSDT", side="long", entry=3.0,
                     is_limit=False, leverage=10, sl=2.9, tps=[3.1, 3.2],
                     margin_pct=7.0, risk_pct=2.0, stop_dist_pct=2.0)
        result = await om.enter(sig, 100.0)
        # 独立 SL 被调用一次；进场单不带 sl_price
        self.assertEqual(adapter.attached_sl, [("LITUSDT", 2.9)])
        self.assertIsNone(adapter.created[0]["sl_price"])
        self.assertEqual(len(result["tp_order_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
