"""风控单测（用户指定公式：张数 = equity × R% ÷ |建仓−止损| ÷ 合约倍数）。"""
import unittest

from autotrade.risk.engine import calc_contract_qty, check_margin_formula
from autotrade.risk.precision import calc_min_qty, split_tier_qty


class TestContractQty(unittest.TestCase):
    def test_order216(self):
        # 訂單216 LITUSDT：equity=1000，R=2%，entry=3.042，SL=2.962，合约倍数=1
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.042, 2.962, 1), 250)

    def test_contract_size_0001(self):
        # 合约倍数为 0.001（如 BTCUSDT 每张 0.001 BTC）
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.042, 2.962, 0.001), 250000)

    def test_zero_stop_distance(self):
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 3.0, 1), 0)

    def test_invalid_contract_size(self):
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 2.9, 0), 0)

    def test_floor(self):
        # 1000×2% ÷ 0.079 = 253.16 币 → 253 张
        self.assertEqual(calc_contract_qty(1000, 2.0, 3.0, 2.921, 1), 253)


class TestMarginFormula(unittest.TestCase):
    def test_order216(self):
        # 2.00/(2.63×10) = 7.60% ≈ 报单 7.61%
        self.assertTrue(check_margin_formula(7.61, 2.00, 2.63, 10))

    def test_order213(self):
        # 1.21/(0.81×10) = 14.94% ≈ 报单 15.00%（上限）
        self.assertTrue(check_margin_formula(15.00, 1.21, 0.81, 10))

    def test_order196(self):
        # 2.00/(1.95×10) = 10.26% ≈ 报单 10.28%
        self.assertTrue(check_margin_formula(10.28, 2.00, 1.95, 10))

    def test_mismatch_rejected(self):
        self.assertFalse(check_margin_formula(10.0, 2.00, 2.63, 10))


class TestSplitTierQty(unittest.TestCase):
    def test_even_split(self):
        # 4 档均分 100 张 → [25, 25, 25, 25]
        self.assertEqual(split_tier_qty(100, 4), [25.0, 25.0, 25.0, 25.0])

    def test_last_tier_takes_remainder(self):
        # 4 档均分 101 张 → 前 3 档 25.25，末档 25.25（末档=总量−前档合计）
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
        # LIT 价格 3.14 → 5/3.14/0.1 = 15.92 → ceil 16 → 1.6
        self.assertEqual(calc_min_qty(3.14, 0.1, 5.0), 1.6)

    def test_zero_price(self):
        self.assertEqual(calc_min_qty(0, 0.1, 5.0), 0.1)

    def test_zero_step(self):
        self.assertEqual(calc_min_qty(3.0, 0, 5.0), 0.0)


if __name__ == "__main__":
    unittest.main()
