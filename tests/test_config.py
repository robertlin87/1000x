"""設定校驗單測：下單倍數只能是整數或小數（純數字）。"""
import tempfile
import unittest
from pathlib import Path

from autotrade.config import (
    DEFAULT_TP_RATIOS,
    load_config,
    parse_multiplier,
    parse_tp_ratios,
)


class TestParseMultiplier(unittest.TestCase):
    def test_integers_and_decimals(self):
        for text, expected in (("1", 1.0), ("1.0", 1.0), ("0.5", 0.5),
                               ("2.75", 2.75), ("0.001", 0.001), ("100", 100.0),
                               (" 1.25 ", 1.25)):
            with self.subTest(text=text):
                self.assertEqual(parse_multiplier(text), expected)

    def test_numeric_types(self):
        self.assertEqual(parse_multiplier(0.5), 0.5)
        self.assertEqual(parse_multiplier(3), 3.0)

    def test_rejects_non_numbers(self):
        for text in ("", "abc", "1a", "-1", "+1", "1e3", "1.", ".5",
                     "1.2.3", "0", "0.0", "nan", "inf", "１", True, None):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_multiplier(text)


class TestLoadConfigMultiplier(unittest.TestCase):
    def test_valid_multiplier_normalized_to_float(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  order_multiplier: 1.25\n", encoding="utf-8")
            self.assertEqual(load_config(str(p)).risk["order_multiplier"], 1.25)

    def test_invalid_multiplier_rejected_at_startup(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  order_multiplier: abc\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(str(p))


class TestParseTpRatios(unittest.TestCase):
    def test_valid_lists(self):
        for value, expected in (
            ([25, 25, 25, 25], [25.0, 25.0, 25.0, 25.0]),
            (["25", "25", "25", "25"], [25.0, 25.0, 25.0, 25.0]),
            ([100, 0, 0, 0], [100.0, 0.0, 0.0, 0.0]),
            ([0, 30, 70, 0], [0.0, 30.0, 70.0, 0.0]),
            ([33.3, 33.3, 33.4, 0], [33.3, 33.3, 33.4, 0.0]),
            ([40.5, 20, 20, 19.5], [40.5, 20.0, 20.0, 19.5]),
        ):
            with self.subTest(value=value):
                self.assertEqual(parse_tp_ratios(value), expected)

    def test_equal_migrates_to_default(self):
        self.assertEqual(parse_tp_ratios("equal"), list(DEFAULT_TP_RATIOS))
        self.assertEqual(parse_tp_ratios("EQUAL"), list(DEFAULT_TP_RATIOS))
        self.assertEqual(parse_tp_ratios(" Equal "), list(DEFAULT_TP_RATIOS))

    def test_rejects(self):
        for value in (
            [25, 25, 25],           # 長度 3
            [25, 25, 25, 25, 0],    # 長度 5
            [24, 25, 25, 25],       # 加總 99
            [25, 25, 25, 26],       # 加總 101
            [30, 30, 30, 30],       # 加總 120
            [-25, 25, 50, 50],      # 負數
            ["25.", "25", "25", "25"],
            [".5", "25", "25", "49.5"],
            ["1e2", 0, 0, 0],
            ["25%", 25, 25, 25],
            [" 25 ", "25", "25", None],
            [True, 25, 25, 50],     # bool 是 int 子類，str(True)="True" 不匹配
            "25,25,25,25",          # 純字串非 equal
            25,                     # 標量
            None,
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_tp_ratios(value)


class TestLoadConfigTpRatios(unittest.TestCase):
    def test_missing_injected_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  order_multiplier: 1.0\n", encoding="utf-8")
            self.assertEqual(load_config(str(p)).risk["tp_ratios"],
                             list(DEFAULT_TP_RATIOS))

    def test_equal_migrated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  tp_ratios: equal\n", encoding="utf-8")
            self.assertEqual(load_config(str(p)).risk["tp_ratios"],
                             list(DEFAULT_TP_RATIOS))

    def test_invalid_falls_back_to_default_without_raise(self):
        # 與 order_multiplier 的「非法即拒」不同：非法比例回退預設、不卡啟動
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  tp_ratios: [30, 30, 30, 30]\n", encoding="utf-8")
            self.assertEqual(load_config(str(p)).risk["tp_ratios"],
                             list(DEFAULT_TP_RATIOS))

    def test_valid_normalized_to_floats(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("risk:\n  tp_ratios: [30, 70, 0, 0]\n", encoding="utf-8")
            self.assertEqual(load_config(str(p)).risk["tp_ratios"],
                             [30.0, 70.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
