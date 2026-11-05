"""風控單測（使用者指定公式：張數 = equity × R% ÷ |建倉−止損| ÷ 合約倍數）。"""
import unittest

from autotrade.risk.engine import calc_contract_qty, check_margin_formula
from autotrade.risk.precision import (
    calc_min_qty,
    exchange_min_qty,
    last_positive_tier,
    plan_tp_tiers,
    round_down_qty,
    split_tier_qty,
)


class TestContractQty(unittest.TestCase):
    def test_order216(self):
        # 訂單216 LITUSDT：equity=1000，R=2%，entry=3.042，SL=2.962，合約倍數=1
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.042, 2.962, 1), 250)

    def test_contract_size_0001(self):
        # 合約倍數為 0.001（如 BTCUSDT 每張 0.001 BTC）
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.042, 2.962, 0.001), 250000)

    def test_zero_stop_distance(self):
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 3.0, 1), 0)

    def test_invalid_contract_size(self):
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 2.9, 0), 0)

    def test_floor(self):
        # 1000×2% ÷ 0.079 = 253.16 幣 → 253 張
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 2.921, 1), 253)


class TestMarginFormula(unittest.TestCase):
    def test_order216(self):
        # 2.00/(2.63×10) = 7.60% ≈ 報單 7.61%
        self.assertTrue(check_margin_formula(7.61, 2.00, 2.63, 10))

    def test_order213(self):
        # 1.21/(0.81×10) = 14.94% ≈ 報單 15.00%（上限）
        self.assertTrue(check_margin_formula(15.00, 1.21, 0.81, 10))

    def test_order196(self):
        # 2.00/(1.95×10) = 10.26% ≈ 報單 10.28%
        self.assertTrue(check_margin_formula(10.28, 2.00, 1.95, 10))

    def test_mismatch_rejected(self):
        self.assertFalse(check_margin_formula(10.0, 2.00, 2.63, 10))


class TestSplitTierQty(unittest.TestCase):
    def test_even_split(self):
        # 4 檔均分 100 張 → [25, 25, 25, 25]
        self.assertEqual(split_tier_qty(100, 4), [25.0, 25.0, 25.0, 25.0])

    def test_last_tier_takes_remainder(self):
        # 4 檔均分 101 張 → 前 3 檔 25.25，末檔 25.25（末檔=總量−前檔合計）
        tiers = split_tier_qty(101, 4)
        self.assertEqual(tiers[-1], 101.0 - sum(tiers[:-1]))
        self.assertAlmostEqual(sum(tiers), 101.0)

    def test_single_tier(self):
        self.assertEqual(split_tier_qty(50, 1), [50.0])

    def test_invalid(self):
        self.assertEqual(split_tier_qty(0, 4), [])
        self.assertEqual(split_tier_qty(10, 0), [])

    def test_ratios_default_25x4(self):
        # 預設比例 25/25/25/25 = 均分
        self.assertEqual(split_tier_qty(100, 4, [25, 25, 25, 25]),
                         [25.0, 25.0, 25.0, 25.0])

    def test_ratios_three_tiers_full_close_on_last(self):
        # 報單 3 檔：前 2 檔按比例，第 3 檔拿走剩餘 50
        self.assertEqual(split_tier_qty(100, 3, [25, 25, 25, 25]),
                         [25.0, 25.0, 50.0])

    def test_ratios_zero_tier_kept_zero(self):
        # 0% 檔 = 0 手（由 plan_tp_tiers 跳過掛單）
        self.assertEqual(split_tier_qty(100, 4, [0, 25, 25, 50]),
                         [0.0, 25.0, 25.0, 50.0])

    def test_ratios_last_tier_remainder_invariant(self):
        tiers = split_tier_qty(101, 4, [30, 70, 0, 0])
        self.assertAlmostEqual(tiers[0], 30.3)
        self.assertAlmostEqual(tiers[1], 70.7)
        self.assertAlmostEqual(tiers[-1], 101.0 - sum(tiers[:-1]))

    def test_ratios_structural_fallback_to_equal(self):
        # 長度不足 / 全 0 → 回退均分
        self.assertEqual(split_tier_qty(100, 4, [25, 25]), [25.0, 25.0, 25.0, 25.0])
        self.assertEqual(split_tier_qty(100, 4, [0, 0, 0, 0]), [25.0, 25.0, 25.0, 25.0])


class TestLastPositiveTier(unittest.TestCase):
    def test_last_nonzero_index(self):
        self.assertEqual(last_positive_tier([100, 0, 0, 0]), 1)
        self.assertEqual(last_positive_tier([30, 70, 0, 0]), 2)
        self.assertEqual(last_positive_tier([25, 25, 50, 0]), 3)
        self.assertEqual(last_positive_tier([25, 25, 25, 25]), 4)
        self.assertEqual(last_positive_tier([40, 0, 60, 0]), 3)  # 中間空檔不算
        self.assertEqual(last_positive_tier([0, 0, 0, 0]), 0)
        self.assertEqual(last_positive_tier(None), 0)
        self.assertEqual(last_positive_tier([]), 0)


class TestPlanTpTiers(unittest.TestCase):
    """TP 掛單規劃：使用者 2026-11-05 逐例確認的驗收語義。"""

    TPS = [3.1213, 3.1788, 3.2411, 3.2856]  # 4 檔報單
    STEP = 0.001

    def _plan(self, qty, tps=None, ratios=None, exchange_min=0.0):
        return plan_tp_tiers(qty, self.TPS if tps is None else tps,
                             ratios, self.STEP, exchange_min)

    def test_equal_split_matches_old_behavior(self):
        # 均分（ratios=None）+ exchange_min=0 → 與舊行為逐檔一致
        self.assertEqual(self._plan(101.0), [(3.1213, 25.25), (3.1788, 25.25),
                                             (3.2411, 25.25), (3.2856, 25.25)])

    def test_only_tp1_full_close(self):
        # 驗收 1：只填 TP1 → TP1 全平，後續檔不掛
        self.assertEqual(self._plan(100.0, ratios=[100, 0, 0, 0]),
                         [(3.1213, 100.0)])

    def test_two_tiers_full_close_on_tp2(self):
        # 驗收 2：填 TP1+TP2 → TP2 全平，TP3/TP4 不掛
        self.assertEqual(self._plan(100.0, ratios=[30, 70, 0, 0]),
                         [(3.1213, 30.0), (3.1788, 70.0)])

    def test_tp4_zero_full_close_on_tp3(self):
        # 驗收 3：TP4 填 0 → TP3 全平
        self.assertEqual(self._plan(100.0, ratios=[25, 25, 25, 0]),
                         [(3.1213, 25.0), (3.1788, 25.0), (3.2411, 50.0)])

    def test_four_tiers_all_filled(self):
        # 驗收 4：四檔全填 → TP1-3 按比例、TP4 全平
        self.assertEqual(self._plan(100.0, ratios=[20, 20, 30, 30]),
                         [(3.1213, 20.0), (3.1788, 20.0), (3.2411, 30.0),
                          (3.2856, 30.0)])

    def test_zero_in_middle(self):
        # 驗收 5：中間有 0 → TP2 跳過，TP3（最後非 0 檔）全平
        self.assertEqual(self._plan(100.0, ratios=[40, 0, 60, 0]),
                         [(3.1213, 40.0), (3.2411, 60.0)])

    def test_signal_two_tiers_full_close_on_signal_last(self):
        # 驗收 6：報單 2 檔 + 填 4 檔 → 報單最後一檔（TP2）全清 75
        self.assertEqual(self._plan(100.0, tps=[3.1213, 3.1788],
                                    ratios=[25, 25, 25, 25]),
                         [(3.1213, 25.0), (3.1788, 75.0)])

    def test_signal_five_tiers_ignored_beyond_four(self):
        # 驗收 7：報單 5 檔 + 填 4 檔 → 只掛 4 檔，TP4 全平，TP5 不掛
        tps5 = self.TPS + [3.3000]
        self.assertEqual(self._plan(100.0, tps=tps5),
                         [(3.1213, 25.0), (3.1788, 25.0), (3.2411, 25.0),
                          (3.2856, 25.0)])

    def test_signal_five_tiers_ratio_full_close_on_tp4(self):
        tps5 = self.TPS + [3.3000]
        self.assertEqual(self._plan(100.0, tps=tps5, ratios=[20, 20, 30, 30]),
                         [(3.1213, 20.0), (3.1788, 20.0), (3.2411, 30.0),
                          (3.2856, 30.0)])

    def test_floor_sweep_absorbs_remainder(self):
        # 比例×qty 向下取整後，剩餘全部流入末檔（Σ 恰 = qty）
        plans = self._plan(101.0, ratios=[50, 50, 0, 0])
        self.assertEqual(plans, [(3.1213, 50.5), (3.1788, 50.5)])
        self.assertEqual(sum(q for _, q in plans), 101.0)

    def test_tier_below_exchange_min_merged_into_sweep(self):
        # 前檔低於交易所最低手數 → 不掛，份額流入末檔（驗收規則 8 的既有規則）
        plans = self._plan(0.4, ratios=[10, 10, 10, 70], exchange_min=0.1)
        self.assertEqual(plans, [(3.2856, 0.4)])

    def test_sweep_below_exchange_min_merged_into_previous(self):
        # 末檔 0.04 < min 0.1 → 併入上一檔（TP3 價格全清）
        plans = self._plan(0.4, ratios=[30, 30, 30, 10], exchange_min=0.1)
        self.assertEqual(plans, [(3.1213, 0.12), (3.1788, 0.12), (3.2411, 0.16)])
        self.assertEqual(sum(q for _, q in plans), 0.4)

    def test_sweep_exactly_min_not_merged(self):
        plans = self._plan(0.4, ratios=[25, 25, 25, 25], exchange_min=0.1)
        self.assertEqual(plans, [(3.1213, 0.1), (3.1788, 0.1),
                                 (3.2411, 0.1), (3.2856, 0.1)])

    def test_sum_equals_qty_always(self):
        for ratios in ([25, 25, 25, 25], [33.3, 33.3, 33.4, 0], [7, 23, 40, 30]):
            for qty in (100.0, 101.0, 0.4, 6.576):
                plans = self._plan(qty, ratios=ratios)
                self.assertAlmostEqual(sum(q for _, q in plans), qty, places=9,
                                       msg=f"{ratios} qty={qty}")

    def test_single_tier(self):
        self.assertEqual(self._plan(50.0, tps=[3.1213]), [(3.1213, 50.0)])

    def test_empty_inputs(self):
        self.assertEqual(self._plan(0.0), [])
        self.assertEqual(self._plan(100.0, tps=[]), [])


class TestExchangeMinQty(unittest.TestCase):
    def test_amount_min_only(self):
        market = {"limits": {"amount": {"min": 0.001}, "cost": {}},
                  "precision": {"amount": 0.001}}
        self.assertEqual(exchange_min_qty(market, 3.0), 0.001)

    def test_cost_min_only(self):
        market = {"limits": {"amount": {}, "cost": {"min": 5.0}},
                  "precision": {"amount": 0.1}}
        self.assertEqual(exchange_min_qty(market, 3.0), 1.7)

    def test_both_take_max(self):
        market = {"limits": {"amount": {"min": 0.01}, "cost": {"min": 5.0}},
                  "precision": {"amount": 0.1}}
        # cost.min → 1.7 > amount.min 0.01
        self.assertEqual(exchange_min_qty(market, 3.0), 1.7)

    def test_neither_returns_zero(self):
        self.assertEqual(exchange_min_qty({"limits": {}}, 3.0), 0.0)


class TestCalcMinQty(unittest.TestCase):
    def test_min_qty(self):
        # 5U / 3.0 / 0.1 = 16.67 → ceil 17 → 1.7
        self.assertEqual(calc_min_qty(3.0, 0.1, 5.0), 1.7)

    def test_lit_like(self):
        # LIT 價格 3.14 → 5/3.14/0.1 = 15.92 → ceil 16 → 1.6
        self.assertEqual(calc_min_qty(3.14, 0.1, 5.0), 1.6)

    def test_zero_price(self):
        self.assertEqual(calc_min_qty(0, 0.1, 5.0), 0.1)

    def test_zero_step(self):
        self.assertEqual(calc_min_qty(3.0, 0, 5.0), 0.0)


class TestRoundDownQty(unittest.TestCase):
    def test_floor_to_step(self):
        self.assertEqual(round_down_qty(125.1239, 0.001), 125.123)
        self.assertEqual(round_down_qty(6.5769, 0.01), 6.57)

    def test_no_float_rounding_drift(self):
        # 浮點 6.576/0.001 = 6575.999999999999，不能被砍成 6.575
        self.assertEqual(round_down_qty(6.576, 0.001), 6.576)
        self.assertEqual(round_down_qty(1.644, 0.001), 1.644)

    def test_already_aligned_unchanged(self):
        self.assertEqual(round_down_qty(250.0, 0.001), 250.0)
        self.assertEqual(round_down_qty(100.0, 1.0), 100.0)

    def test_missing_step_returns_value(self):
        self.assertEqual(round_down_qty(3.14159, None), 3.14159)
        self.assertEqual(round_down_qty(3.14159, 0), 3.14159)


if __name__ == "__main__":
    unittest.main()
