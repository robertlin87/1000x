"""設定校驗單測：下單倍數只能是整數或小數（純數字）。"""
import tempfile
import unittest
from pathlib import Path

from autotrade.config import load_config, parse_multiplier


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


if __name__ == "__main__":
    unittest.main()
