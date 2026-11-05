"""嚮導自檢錯誤提示單測：底層異常要翻成使用者能自己動手的中文指引。"""
import unittest

from autotrade.gui.wizard import friendly_selfcheck_error


class TestFriendlySelfcheckError(unittest.TestCase):
    def test_session_locked(self):
        s = friendly_selfcheck_error("TG 自檢失敗", Exception("database is locked"))
        self.assertIn("關閉其他", s)
        self.assertIn("會話", s)

    def test_bybit_clock_skew(self):
        e = Exception(
            'bybit {"retCode":10002,"retMsg":"invalid request, please check your '
            'server timestamp or recv_window","req_timestamp[1793788562531]}'
        )
        s = friendly_selfcheck_error("交易所自檢失敗", e)
        self.assertIn("時間", s)
        self.assertIn("立即同步", s)
        self.assertIn("10002", s)

    def test_unknown_error_keeps_original_message(self):
        s = friendly_selfcheck_error("交易所自檢失敗", Exception("connection refused"))
        self.assertIn("connection refused", s)


if __name__ == "__main__":
    unittest.main()
