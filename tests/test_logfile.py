"""日誌脫敏單測：使用者可見輸出不得出現本機網絡連線細節。"""
import logging
import unittest

from autotrade.logfile import PrivacyFilter


def _record(msg, *args, name="autotrade.network"):
    return logging.LogRecord(name, logging.INFO, "", 0, msg, args, None)


class TestPrivacyFilter(unittest.TestCase):
    def setUp(self):
        self.f = PrivacyFilter()

    def test_own_proxy_log_scrubbed(self):
        r = _record("檢測到存活代理：%s:%s", "127.0.0.1", 7897, name="autotrade.proxy")
        self.assertTrue(self.f.filter(r))
        out = r.getMessage()
        self.assertNotIn("代理", out)
        self.assertNotIn("7897", out)
        self.assertEqual(r.name, "autotrade.network")

    def test_third_party_warning_scrubbed(self):
        r = _record("Could not connect to proxy 127.0.0.1:17890",
                    name="telethon.network.mtprotosender")
        self.assertTrue(self.f.filter(r))
        out = r.getMessage()
        self.assertNotIn("proxy", out.lower())
        self.assertNotIn("17890", out)
        self.assertIn("Could not connect", out)  # 診斷信息仍保留

    def test_plain_message_untouched(self):
        r = _record("已進場 訂單216 LITUSDT qty=250")
        self.assertTrue(self.f.filter(r))
        self.assertEqual(r.getMessage(), "已進場 訂單216 LITUSDT qty=250")

    def test_vpn_and_related_words_scrubbed(self):
        for word in ("VPN", "Clash", "v2rayN", "翻牆", "被牆", "socks5"):
            with self.subTest(word=word):
                r = _record(f"連線失敗：{word}")
                self.f.filter(r)
                self.assertNotIn(word, r.getMessage())


if __name__ == "__main__":
    unittest.main()
