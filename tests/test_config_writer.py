"""config_writer 單測：生成結構正確（passphrase/db_path/dry_run），
只寫目前一家交易所，round-trip 寫回保留註釋與其他欄位。"""
import tempfile
import unittest
from pathlib import Path

from autotrade.config_writer import (
    SESSION_NAME,
    blank_exchange_fields,
    build_config,
    write_config,
)


class TestBuildConfig(unittest.TestCase):
    def test_structure_keys(self):
        cfg = build_config(
            api_id=123, api_hash="abc", exchange="bybit",
            credentials={"apiKey": "k", "secret": "s"}, order_multiplier=2.0,
        )
        self.assertEqual(cfg["telegram"]["api_id"], 123)
        self.assertEqual(cfg["telegram"]["api_hash"], "abc")
        self.assertEqual(cfg["telegram"]["session_name"], SESSION_NAME)
        self.assertFalse(cfg["dry_run"])
        self.assertEqual(cfg["exchanges"]["active"], "bybit")
        self.assertEqual(cfg["storage"]["db_path"], "data/autotrade.db")
        self.assertEqual(cfg["risk"]["order_multiplier"], 2.0)
        # 未傳 tp_ratios → 預設 25/25/25/25（無條件覆蓋模板值）
        self.assertEqual(cfg["risk"]["tp_ratios"], [25.0, 25.0, 25.0, 25.0])

    def test_tp_ratios_override(self):
        cfg = build_config(
            api_id=1, api_hash="h", exchange="bybit",
            credentials={"apiKey": "k", "secret": "s"}, order_multiplier=1.0,
            tp_ratios=[40, 20, 20, 20],
        )
        self.assertEqual(cfg["risk"]["tp_ratios"], [40.0, 20.0, 20.0, 20.0])

    def test_tp_ratios_written_and_readback(self):
        # 落盤後經 load_config 回讀（不依賴 ruamel 序列化文本格式）
        import tempfile as _tf

        from autotrade.config import load_config

        cfg = build_config(
            api_id=1, api_hash="h", exchange="bybit",
            credentials={"apiKey": "k", "secret": "s"}, order_multiplier=1.0,
            tp_ratios=[50, 0, 25, 25],
        )
        with _tf.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            write_config(p, cfg)
            self.assertEqual(load_config(str(p)).risk["tp_ratios"],
                             [50.0, 0.0, 25.0, 25.0])

    def test_only_active_exchange_has_keys(self):
        creds = {"apiKey": "K", "secret": "S", "passphrase": "P"}
        cfg = build_config(
            api_id=1, api_hash="h", exchange="bitget",
            credentials=creds, order_multiplier=1.0,
        )
        bybit = cfg["exchanges"]["bybit"]
        self.assertEqual(bybit["apiKey"], "")
        self.assertEqual(bybit["secret"], "")
        self.assertNotIn("passphrase", bybit)
        bitget = cfg["exchanges"]["bitget"]
        self.assertEqual(bitget["apiKey"], "K")
        self.assertEqual(bitget["secret"], "S")
        self.assertEqual(bitget["passphrase"], "P")
        for name in ("binance", "gate", "deepcoin", "bitunix"):
            ex = cfg["exchanges"][name]
            self.assertTrue(all(v == "" for v in ex.values()), name)
        self.assertIn("passphrase", cfg["exchanges"]["deepcoin"])

    def test_no_password_dead_key(self):
        cfg = build_config(
            api_id=1, api_hash="h", exchange="bybit",
            credentials={"apiKey": "k", "secret": "s"}, order_multiplier=1.0,
        )
        for name in cfg["exchanges"]:
            self.assertNotIn("password", cfg["exchanges"][name])

    def test_blank_exchange_fields(self):
        bf = blank_exchange_fields("binance", {"apiKey": "K", "secret": "S"})
        self.assertEqual(bf["binance"]["apiKey"], "K")
        self.assertEqual(bf["bybit"]["apiKey"], "")
        self.assertIn("passphrase", bf["bitget"])
        self.assertIn("passphrase", bf["deepcoin"])
        self.assertNotIn("passphrase", bf["bybit"])


class TestWriteConfig(unittest.TestCase):
    def test_round_trip_preserves_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("# 頂部註釋\nrisk:\n  order_multiplier: 1.0\n", encoding="utf-8")
            cfg = build_config(
                api_id=9, api_hash="x", exchange="bybit",
                credentials={"apiKey": "k", "secret": "s"}, order_multiplier=1.0,
            )
            write_config(p, cfg)
            text = p.read_text(encoding="utf-8")
            self.assertIn("# 頂部註釋", text)
            self.assertIn("api_id: 9", text)

    def test_merge_keeps_other_sections(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text(
                "telegram:\n  api_id: 1\n  api_hash: a\n  proxy:\n    addr: 1.2.3.4\n"
                "exchanges:\n  active: bybit\n  proxy:\n    port: 9999\n"
                "risk:\n  order_multiplier: 1.0\n",
                encoding="utf-8",
            )
            write_config(p, {"telegram": {"api_id": 2, "api_hash": "b"}})
            text = p.read_text(encoding="utf-8")
            self.assertIn("addr: 1.2.3.4", text)
            self.assertIn("port: 9999", text)
            self.assertIn("api_id: 2", text)


if __name__ == "__main__":
    unittest.main()
