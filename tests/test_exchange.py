"""多交易所接入單測：schema 完整性、工廠分發、非 attached 進場分支。"""
import unittest
from unittest.mock import MagicMock

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
        # 不需要 passphrase 的所不報錯
        GateAdapter("k", "s")
        BinanceAdapter("k", "s")

    def test_unknown_exchange(self):
        with self.assertRaises(NotImplementedError):
            get_adapter("kraken", {})


class TestNonAttachedEnter(unittest.IsolatedAsyncioTestCase):
    """非 attached 交易所：進場走獨立 SL 掛單分支。"""

    async def test_attach_sl_called_after_entry(self):
        from tests.test_execution import StubAdapter  # 複用可控假適配器
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
        # 獨立 SL 被調用一次；進場單不帶 sl_price
        self.assertEqual(adapter.attached_sl, [("LITUSDT", 2.9)])
        self.assertIsNone(adapter.created[0]["sl_price"])
        self.assertEqual(len(result["tp_order_ids"]), 2)


class TestBybitClock(unittest.IsolatedAsyncioTestCase):
    """Bybit 10002：本機時鐘比服務器慢 > recvWindow 會被拒單。"""

    async def test_recv_window_widened(self):
        a = BybitAdapter("k", "s")
        self.assertGreaterEqual(a._ex.options["recvWindow"], 20000)

    async def test_time_difference_loaded_once_and_applied(self):
        a = BybitAdapter("k", "s")
        a._ex.load_markets = MagicMock()

        def _sync():
            a._ex.options["timeDifference"] = -5195  # 本機慢 5.195 秒
            return -5195

        a._ex.load_time_difference = MagicMock(side_effect=_sync)
        await a._ensure_markets()
        await a._ensure_markets()
        a._ex.load_time_difference.assert_called_once()
        # ccxt.bybit.nonce() = milliseconds() - timeDifference，校準後時間戳前移
        self.assertGreater(a._ex.nonce() - a._ex.milliseconds(), 5000)

    async def test_time_sync_failure_does_not_break_private_calls(self):
        a = BybitAdapter("k", "s")
        a._ex.load_markets = MagicMock()
        a._ex.load_time_difference = MagicMock(side_effect=RuntimeError("offline"))
        await a._ensure_markets()
        a._ex.load_markets.assert_called_once()


if __name__ == "__main__":
    unittest.main()
