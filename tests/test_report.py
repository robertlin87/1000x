"""问题报告单测：错误摘要去重聚合、密钥脱敏、temp 每日清理。"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from datetime import datetime, timedelta

from autotrade import paths
from autotrade.report import _error_summary, _scrub, collect_report


def _lines(samples):
    """构造 (ts, level, name, msg, raw) 五元组序列。"""
    out = []
    for ts, level, name, msg in samples:
        raw = f"{ts},000 {level} {name}: {msg}"
        out.append((ts, level, name, msg, raw))
    return out


class TestErrorSummary(unittest.TestCase):
    def test_dedup_aggregation(self):
        lines = _lines([
            ("2026-11-04 08:00:00", "ERROR", "autotrade.x", "连接超时"),
            ("2026-11-04 08:01:00", "ERROR", "autotrade.x", "连接超时"),
            ("2026-11-04 08:02:00", "ERROR", "autotrade.x", "连接超时"),
            ("2026-11-04 09:00:00", "WARNING", "autotrade.y", "另一类告警"),
        ])
        summary = _error_summary(lines)
        self.assertIn("[发生 3 次]", summary)          # 同一错误聚合为一行
        self.assertIn("连接超时", summary)
        self.assertIn("[发生 1 次]", summary)          # 不同错误各自一行
        self.assertEqual(summary.count("[发生"), 2)

    def test_info_not_in_summary(self):
        lines = _lines([("2026-11-04 08:00:00", "INFO", "autotrade.x", "正常日志")])
        self.assertIn("无 ERROR/WARNING", _error_summary(lines))


class TestScrub(unittest.TestCase):
    def test_secret_replaced(self):
        text = "apiKey=FAKEKEY123 下单失败\nsecret=Ddw111"
        scrubbed = _scrub(text, ["FAKEKEY123", "Ddw111"])
        self.assertNotIn("FAKEKEY123", scrubbed)
        self.assertNotIn("Ddw111", scrubbed)
        self.assertIn("***", scrubbed)


class TestCleanupTempDir(unittest.TestCase):
    def test_only_today_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            today = d / "today.txt"
            yesterday = d / "yesterday.txt"
            twodaysago = d / "old.txt"
            today.write_text("t", encoding="utf-8")
            yesterday.write_text("y", encoding="utf-8")
            twodaysago.write_text("o", encoding="utf-8")
            old_ts = (datetime.now() - timedelta(days=1)).timestamp()
            os_old = (datetime.now() - timedelta(days=2)).timestamp()
            import os
            os.utime(yesterday, (old_ts, old_ts))
            os.utime(twodaysago, (os_old, os_old))
            with mock.patch("autotrade.paths.temp_dir", return_value=d):
                paths.cleanup_temp_dir()
            self.assertEqual(sorted(p.name for p in d.iterdir()), ["today.txt"])


class TestCollectReport(unittest.TestCase):
    def test_report_structure_and_scrub(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            logfile = d / "autotrade.log"
            logfile.write_text(
                "2026-11-04 08:00:00,000 ERROR autotrade.x: FAKEKEY123 下单失败\n"
                "2026-11-04 08:01:00,000 ERROR autotrade.x: FAKEKEY123 下单失败\n",
                encoding="utf-8",
            )
            with mock.patch("autotrade.paths.temp_dir", return_value=d), \
                 mock.patch("autotrade.report._secret_values", return_value=["FAKEKEY123"]):
                report = collect_report()
            self.assertIn("加密林教头VIP跟单助手 问题报告", report)
            self.assertIn("[发生 2 次]", report)
            self.assertNotIn("FAKEKEY123", report)
            self.assertIn("***", report)


if __name__ == "__main__":
    unittest.main()
