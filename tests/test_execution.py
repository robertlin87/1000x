"""M2 执行层单测：风控 validate、PositionTracker、OrderManager、TriggerRouter、Watchdog。"""
import unittest

from autotrade.exchange.noop import NoopAdapter
from autotrade.execution.order_manager import OrderManager
from autotrade.execution.position_tracker import PositionTracker, PositionState
from autotrade.execution.trigger_router import TriggerRouter
from autotrade.execution.watchdog import Watchdog
from autotrade.notify.notifier import Notifier
from autotrade.parser.entry_parser import Signal
from autotrade.risk.engine import validate


class StubAdapter(NoopAdapter):
    """可控假适配器：position/positions/open_orders 可注入，记录撤单与下单动作。"""

    def __init__(self, position=None, positions=None, open_orders=None, ticker=1.0):
        super().__init__()
        self.position = position
        self.positions = positions or []
        self.open_orders = open_orders or []
        self.ticker = ticker
        self.cancelled: list[str] = []
        self.cancelled_ids: list[str] = []
        self.created: list[dict] = []
        self.amended: list[tuple[str, float]] = []

    async def fetch_position(self, symbol: str) -> dict | None:
        return self.position

    async def fetch_all_positions(self) -> list[dict]:
        return self.positions

    async def fetch_ticker(self, symbol: str) -> float:
        return self.ticker

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        return self.open_orders

    async def cancel_all_for_symbol(self, symbol: str) -> None:
        self.cancelled.append(symbol)

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        self.cancelled_ids.append(order_id)

    async def amend_order(self, order_id: str, symbol: str, **kwargs) -> None:
        self.amended.append((symbol, kwargs.get("sl_price")))

    async def create_order(self, o) -> str:
        self.created.append({"symbol": o.symbol, "side": o.side, "qty": o.qty,
                             "reduce_only": o.reduce_only, "sl_price": o.sl_price,
                             "price": o.price, "order_type": o.order_type})
        return f"stub-{len(self.created)}"


def make_signal(**kw) -> Signal:
    base = dict(order_id="216", symbol="LITUSDT", side="long", entry=3.042,
                is_limit=False, leverage=10, sl=2.962,
                tps=[3.1213, 3.1788, 3.2411, 3.2856],
                margin_pct=7.61, risk_pct=2.00, stop_dist_pct=2.63, analyst="Lazycat")
    base.update(kw)
    return Signal(**base)


class RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__(dry_run=False)
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


class TestRiskValidate(unittest.TestCase):
    def test_accept_and_qty(self):
        d = validate(make_signal(), 1000.0, 1.0)
        self.assertTrue(d.accepted)
        self.assertEqual(d.qty, 250)

    def test_analyst_not_allowed(self):
        d = validate(make_signal(), 1000.0, 1.0,
                     analysts_cfg={"allow_all": False, "list": ["Trader X"]})
        self.assertFalse(d.accepted)
        self.assertIn("分析师", d.reason)

    def test_reverse_signal(self):
        positions = [{"symbol": "LITUSDT", "side": "short"}]
        d = validate(make_signal(), 1000.0, 1.0, open_positions=positions)
        self.assertFalse(d.accepted)
        self.assertIn("反向", d.reason)

    def test_concurrent_limit(self):
        positions = [
            {"symbol": "AUSDT", "side": "long"},
            {"symbol": "BUSDT", "side": "long"},
            {"symbol": "CUSDT", "side": "long"},
        ]
        d = validate(make_signal(), 1000.0, 1.0, open_positions=positions,
                     risk_cfg={"max_concurrent_positions": 3})
        self.assertFalse(d.accepted)
        self.assertIn("并发", d.reason)

    def test_margin_mismatch(self):
        d = validate(make_signal(margin_pct=50.0), 1000.0, 1.0)
        self.assertFalse(d.accepted)
        self.assertIn("保证金", d.reason)

    def test_min_notional(self):
        d = validate(make_signal(), 100.0, 1.0, risk_cfg={"min_notional": 200.0})
        self.assertFalse(d.accepted)
        self.assertIn("名义值", d.reason)

    def test_daily_loss_limit(self):
        d = validate(make_signal(), 1000.0, 1.0, daily_pnl=-60.0,
                     risk_cfg={"daily_loss_pct": 5.0})
        self.assertFalse(d.accepted)
        self.assertIn("亏损", d.reason)


class TestPositionTracker(unittest.TestCase):
    def test_lifecycle(self):
        t = PositionTracker()
        p = t.open("LITUSDT", "long", 100.0, 3.042, 2.962)
        self.assertEqual(p.state, PositionState.PENDING)
        t.mark_filled("LITUSDT")
        self.assertEqual(p.state, PositionState.FILLED)
        t.on_tp_hit("LITUSDT", 25.0)
        self.assertEqual(p.state, PositionState.PARTIAL_TP)
        self.assertEqual(p.tp_hit_count, 1)
        self.assertEqual(p.remaining_qty, 75.0)
        t.on_breakeven("LITUSDT", 3.0)
        self.assertEqual(p.state, PositionState.BREAKEVEN)
        t.on_close("LITUSDT")
        self.assertEqual(p.state, PositionState.CLOSED)
        self.assertEqual(p.remaining_qty, 0.0)

    def test_last_tp_closes(self):
        t = PositionTracker()
        t.open("XUSDT", "long", 10.0, 1.0)
        t.on_tp_hit("XUSDT", 10.0)
        self.assertEqual(t.get("XUSDT").state, PositionState.CLOSED)


class TestOrderManager(unittest.IsolatedAsyncioTestCase):
    async def test_enter_tiers(self):
        om = OrderManager(NoopAdapter())
        result = await om.enter(make_signal(), 250.0)
        self.assertEqual(result["qty"], 250.0)
        self.assertEqual(len(result["tp_order_ids"]), 4)


class TestApplyModify(unittest.IsolatedAsyncioTestCase):
    """✏️ 訂單修改：跟随分析师逐项修改，只动变化项（规则 2026-11-04）。"""

    OLD_TPS = [0.03776, 0.039226, 0.041059, 0.045825]

    def _adapter(self, open_orders=None, ticker=0.037):
        return StubAdapter(
            position={"symbol": "STARUSDT", "side": "long", "qty": 4.0},
            open_orders=open_orders or [],
            ticker=ticker,
        )

    async def test_changed_tier_replaced(self):
        # 只改 TP4：撤旧 0.045825 挂单、按新价 0.0608 重挂，数量不变
        adapter = self._adapter(open_orders=[
            {"id": "tp4", "type": "limit", "reduce_only": True, "price": 0.045825, "qty": 1.0},
        ], ticker=0.037)
        om = OrderManager(adapter)
        fields = {"entry": 0.03666,
                  "tps": [(1, 0.03776), (2, 0.039226), (3, 0.041059), (4, 0.0608)],
                  "sl": 0.03556}
        await om.apply_modify("STARUSDT", "long", fields, self.OLD_TPS, 0.03556)
        self.assertEqual(adapter.cancelled_ids, ["tp4"])
        reorders = [c for c in adapter.created if c["reduce_only"]]
        self.assertEqual(len(reorders), 1)
        self.assertAlmostEqual(reorders[0]["price"], 0.0608)
        self.assertAlmostEqual(reorders[0]["qty"], 1.0)
        self.assertEqual(adapter.amended, [])  # SL 未变

    async def test_unchanged_tiers_untouched(self):
        adapter = self._adapter(open_orders=[
            {"id": "tp4", "type": "limit", "reduce_only": True, "price": 0.0608, "qty": 1.0},
        ], ticker=0.037)
        om = OrderManager(adapter)
        fields = {"tps": [(1, 0.03776), (2, 0.039226), (3, 0.041059), (4, 0.0608)],
                  "sl": 0.03556}
        await om.apply_modify("STARUSDT", "long", fields, self.OLD_TPS, 0.03556)
        self.assertEqual(adapter.cancelled_ids, [])
        self.assertEqual([c for c in adapter.created if c["reduce_only"]], [])

    async def test_invalid_new_price_skipped(self):
        # 新 TP4 低于现价（做多）→ 立即成交风险，跳过重挂并告警
        adapter = self._adapter(open_orders=[
            {"id": "tp4", "type": "limit", "reduce_only": True, "price": 0.045825, "qty": 1.0},
        ], ticker=0.05)
        om = OrderManager(adapter)
        fields = {"tps": [(4, 0.048)], "sl": 0.03556}
        await om.apply_modify("STARUSDT", "long", fields, self.OLD_TPS, 0.03556)
        self.assertEqual([c for c in adapter.created if c["reduce_only"]], [])

    async def test_sl_changed_amended(self):
        adapter = self._adapter(open_orders=[], ticker=0.037)
        om = OrderManager(adapter)
        fields = {"tps": [(1, 0.03776)], "sl": 0.03700}
        await om.apply_modify("STARUSDT", "long", fields, self.OLD_TPS, 0.03556)
        self.assertEqual(adapter.amended, [("STARUSDT", 0.03700)])


class TestCloseAllResidual(unittest.IsolatedAsyncioTestCase):
    """规则 2026-11-04：全平后残留 reduce-only 挂单必须撤。"""

    async def test_no_position_but_residual_orders_cancel(self):
        adapter = StubAdapter(
            position=None,
            open_orders=[{"id": "tp1", "reduce_only": True}, {"id": "tp2", "reduce_only": True}],
        )
        om = OrderManager(adapter)
        closed = await om.close_all("LITUSDT")
        self.assertFalse(closed)  # 无持仓可平
        self.assertEqual(adapter.cancelled, ["LITUSDT"])  # 但残留挂单被撤
        self.assertEqual(adapter.created, [])  # 没有市价平仓动作

    async def test_position_closed_and_cancelled(self):
        adapter = StubAdapter(position={"symbol": "LITUSDT", "side": "long", "qty": 10.0})
        om = OrderManager(adapter)
        closed = await om.close_all("LITUSDT")
        self.assertTrue(closed)
        self.assertEqual(adapter.created[0]["side"], "sell")
        self.assertEqual(adapter.created[0]["qty"], 10.0)
        self.assertEqual(adapter.created[0]["reduce_only"], True)
        self.assertEqual(adapter.cancelled, ["LITUSDT"])

    async def test_nothing_to_do(self):
        adapter = StubAdapter(position=None, open_orders=[])
        om = OrderManager(adapter)
        closed = await om.close_all("LITUSDT")
        self.assertFalse(closed)
        self.assertEqual(adapter.cancelled, [])


class TestWatchdog(unittest.IsolatedAsyncioTestCase):
    """看护轮询（无状态）：无持仓 + reduce-only 残留 → 撤；部分止盈/进场挂单不动。"""

    def _setup(self, adapter):
        notifier = RecordingNotifier()
        return Watchdog(adapter, notifier), notifier

    async def test_full_close_residual_cancelled(self):
        adapter = StubAdapter(
            positions=[],
            open_orders=[{"id": "tp3", "symbol": "LITUSDT", "reduce_only": True}],
        )
        wd, notifier = self._setup(adapter)
        await wd.tick()
        self.assertEqual(adapter.cancelled, ["LITUSDT"])
        self.assertTrue(any("残留挂单" in s for s in notifier.sent), notifier.sent)

    async def test_position_alive_keeps_orders(self):
        # 持仓还在（部分止盈状态）：同 symbol 的 reduce-only 挂单不撤
        adapter = StubAdapter(
            positions=[{"symbol": "LITUSDT", "side": "long", "qty": 6.0}],
            open_orders=[{"id": "tp3", "symbol": "LITUSDT", "reduce_only": True}],
        )
        wd, _ = self._setup(adapter)
        await wd.tick()
        self.assertEqual(adapter.cancelled, [])

    async def test_pending_entry_kept(self):
        # 无持仓 + 只有非 reduce-only 挂单 = 进场限价单还在等，不撤
        adapter = StubAdapter(
            positions=[],
            open_orders=[{"id": "entry", "symbol": "LITUSDT", "reduce_only": False}],
        )
        wd, _ = self._setup(adapter)
        await wd.tick()
        self.assertEqual(adapter.cancelled, [])

    async def test_other_symbol_residual(self):
        # A 币有持仓、B 币残留挂单：只撤 B
        adapter = StubAdapter(
            positions=[{"symbol": "AUSDT", "side": "long", "qty": 1.0}],
            open_orders=[
                {"id": "tp_a", "symbol": "AUSDT", "reduce_only": True},
                {"id": "tp_b", "symbol": "BUSDT", "reduce_only": True},
            ],
        )
        wd, _ = self._setup(adapter)
        await wd.tick()
        self.assertEqual(adapter.cancelled, ["BUSDT"])


class TestTriggerRouter(unittest.IsolatedAsyncioTestCase):
    async def test_signal_enter(self):
        notifier = RecordingNotifier()
        adapter = StubAdapter()
        router = TriggerRouter(adapter, OrderManager(adapter), notifier)
        await router.on_signal(make_signal())
        self.assertTrue(any("已进场" in s for s in notifier.sent), notifier.sent)
        # 开仓单 + 4 档 TP 单
        self.assertEqual(len(adapter.created), 5)
        self.assertEqual(adapter.created[0]["side"], "buy")
        self.assertEqual(adapter.created[0]["sl_price"], 2.962)

    async def test_signal_rejected_by_risk(self):
        notifier = RecordingNotifier()
        adapter = StubAdapter()
        router = TriggerRouter(adapter, OrderManager(adapter), notifier,
                               analysts_cfg={"allow_all": False, "list": ["Other"]})
        await router.on_signal(make_signal())
        self.assertTrue(any("拒单" in s for s in notifier.sent), notifier.sent)
        self.assertEqual(adapter.created, [])

    async def test_reverse_signal_uses_exchange_positions(self):
        # 交易所已有 LIT 空仓：做多报单应被反向信号风控拒掉（无本地状态）
        notifier = RecordingNotifier()
        adapter = StubAdapter(positions=[{"symbol": "LITUSDT", "side": "short", "qty": 1.0}])
        router = TriggerRouter(adapter, OrderManager(adapter), notifier)
        await router.on_signal(make_signal())
        self.assertTrue(any("反向" in s for s in notifier.sent), notifier.sent)
        self.assertEqual(adapter.created, [])

    async def test_sl_hit_event_cancels_residual(self):
        # ❌ 止損 通知 = 全平场景：无持仓但有残留挂单 → 撤单
        notifier = RecordingNotifier()
        adapter = StubAdapter(
            position=None,
            open_orders=[{"id": "tp2", "reduce_only": True}],
        )
        router = TriggerRouter(adapter, OrderManager(adapter), notifier)
        await router.on_event("352", "NEARUSDT", "sl_hit", None, 4.91)
        self.assertEqual(adapter.cancelled, ["NEARUSDT"])
        self.assertTrue(any("全平" in s for s in notifier.sent), notifier.sent)

    async def test_order_multiplier_scales_qty(self):
        # 下单倍数 0.5：R 减半，手数 250 → 125
        notifier = RecordingNotifier()
        adapter = StubAdapter()
        router = TriggerRouter(adapter, OrderManager(adapter), notifier,
                               risk_cfg={"order_multiplier": 0.5})
        await router.on_signal(make_signal())
        entry = adapter.created[0]
        self.assertAlmostEqual(entry["qty"], 125.0)

    async def test_qty_below_min_uses_min_times_tiers(self):
        # 手数低于最低手数 → 按最低手数 × TP档数 下单
        class LowEquityStub(StubAdapter):
            async def fetch_equity(self):
                return 4.0  # 风控手数 = floor(4×2% ÷ 0.08) = 1 < 最低手数

        notifier = RecordingNotifier()
        adapter = LowEquityStub()
        router = TriggerRouter(adapter, OrderManager(adapter), notifier,
                               risk_cfg={"min_notional": 0.5})
        await router.on_signal(make_signal())
        # 最低手数按 min_cost=5U 折算 ≈ 1.644，低于它则按 ×TP档数(4) 下单
        self.assertAlmostEqual(adapter.created[0]["qty"], 1.644 * 4, delta=0.01)

    async def test_qty_above_max_capped(self):
        # 手数高于最高手数 → 按最高手数下单
        class MaxLimitedStub(StubAdapter):
            async def fetch_market(self, symbol):
                m = await super().fetch_market(symbol)
                m["limits"] = {"amount": {"min": None, "max": 100.0}, "cost": {"min": 5.0}}
                return m

        notifier = RecordingNotifier()
        adapter = MaxLimitedStub()
        router = TriggerRouter(adapter, OrderManager(adapter), notifier)
        await router.on_signal(make_signal())
        self.assertEqual(adapter.created[0]["qty"], 100.0)


if __name__ == "__main__":
    unittest.main()
