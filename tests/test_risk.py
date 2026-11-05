"""風控單測（使用者指定公式：張數 = equity × R% ÷ |建倉−止損| ÷ 合約倍數）。"""
import unittest

from autotrade.risk.engine import calc_contract_qty, check_margin_formula
from autotrade.risk.precision import calc_min_qty, round_down_qty, split_tier_qty


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
