"""代理动态解析单测（纯函数部分；系统代理自动检测依赖 winreg 环境，不在此断言具体值）。"""
import unittest

from autotrade.proxy import _parse_proxy_server, _split_host_port, resolve_proxy


class TestParseProxyServer(unittest.TestCase):
    def test_single_no_scheme(self):
        self.assertEqual(_parse_proxy_server("127.0.0.1:7897"), ("127.0.0.1", 7897))

    def test_multi_scheme_prefers_socks(self):
        server = "http=127.0.0.1:7897;https=127.0.0.1:7897;socks=127.0.0.1:1080"
        self.assertEqual(_parse_proxy_server(server), ("127.0.0.1", 1080))

    def test_empty(self):
        self.assertIsNone(_parse_proxy_server(""))
        self.assertIsNone(_parse_proxy_server("; ;"))

    def test_split_host_port(self):
        self.assertEqual(_split_host_port("127.0.0.1:17890"), ("127.0.0.1", 17890))
        self.assertIsNone(_split_host_port(""))
        self.assertIsNone(_split_host_port("no_port"))
        self.assertIsNone(_split_host_port("127.0.0.1:notanum"))


class TestResolveProxy(unittest.TestCase):
    def test_explicit_config(self):
        cfg = {"enabled": True, "type": "socks5", "addr": "127.0.0.1", "port": 9999}
        self.assertEqual(resolve_proxy(cfg, "socks5"), ("socks5", "127.0.0.1", 9999))

    def test_bad_type_raises(self):
        cfg = {"enabled": True, "type": "bad", "addr": "127.0.0.1", "port": 9999}
        with self.assertRaises(ValueError):
            resolve_proxy(cfg, "socks5")

    def test_disabled_or_none_no_exception(self):
        # enabled=false / None 时走系统代理自动检测，结果依环境而定；
        # 这里仅断言不抛异常且返回值格式合法（None 或三元组）。
        for cfg in ({"enabled": False}, None):
            result = resolve_proxy(cfg, "socks5")
            self.assertTrue(result is None or (isinstance(result, tuple) and len(result) == 3))


if __name__ == "__main__":
    unittest.main()
