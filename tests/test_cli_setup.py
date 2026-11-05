"""cli_setup 單測：首次嚮導全流程、選單 1/2/3/回車各分支、換所清空舊所、空值取消、非交互跳過。

大量 mock 輸入與異步自檢，不觸碰真實 TG / 交易所網絡。
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autotrade import cli_setup
from autotrade.config import load_config
from autotrade.config_writer import build_config, write_config


def _make_fake_run(results):
    """mock asyncio.run：吃掉真實協程（避免 'never awaited' 警告）並返回預置結果。"""
    it = iter(results)

    def _run(coro):
        if hasattr(coro, "close"):
            coro.close()
        return next(it)

    return _run


class _Base(unittest.TestCase):
    def _config_path(self, exchange="bybit", api_key="", secret="") -> Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "config.yaml"
        cfg = build_config(
            api_id=1, api_hash="h", exchange=exchange,
            credentials={"apiKey": api_key, "secret": secret}, order_multiplier=1.0,
        )
        write_config(p, cfg)
        return p

    def _patch_io(self, read_text=None, menu_key=None, choose=None, interactive=True,
                  asyncio_runs=None):
        patchers = [
            mock.patch("autotrade.cli_setup.is_interactive", return_value=interactive),
            mock.patch("autotrade.cli_setup.read_text", side_effect=read_text or []),
            mock.patch("autotrade.cli_setup.read_menu_key", side_effect=menu_key or []),
            mock.patch("autotrade.cli_setup.choose_from_list", side_effect=choose or []),
            mock.patch("autotrade.cli_setup.asyncio.run",
                       side_effect=_make_fake_run(asyncio_runs or [])),
            mock.patch("autotrade.cli_setup.prompt_multiplier"),
            mock.patch("autotrade.cli_setup.prompt_tp_ratios"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)


class TestFirstTimeSetup(_Base):
    def test_full_flow_writes_correct_config(self):
        self._patch_io(
            read_text=["123", "myhash", "K", "S"],
            choose=[0],  # bybit
            asyncio_runs=[(True, "tg ok"), (True, "ex ok")],
        )
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "config.yaml"
            cli_setup.run_first_time_setup(target)
            cfg = load_config(str(target))
            self.assertEqual(cfg.telegram["api_id"], 123)
            self.assertEqual(cfg.telegram["api_hash"], "myhash")
            self.assertEqual(cfg.exchanges["active"], "bybit")
            self.assertEqual(cfg.exchanges["bybit"]["apiKey"], "K")
            self.assertEqual(cfg.exchanges["bybit"]["secret"], "S")
            self.assertEqual(cfg.storage["db_path"], "data/autotrade.db")
            self.assertFalse(cfg.dry_run)
            self.assertEqual(cfg.risk["order_multiplier"], 1.0)
            # 首啟寫入預設止盈部位比例 25/25/25/25
            self.assertEqual(cfg.risk["tp_ratios"], [25.0, 25.0, 25.0, 25.0])
            # 其它交易所應為空
            for name in ("binance", "bitget", "gate", "deepcoin", "bitunix"):
                self.assertTrue(all(v == "" for v in cfg.exchanges[name].values()), name)

    def test_non_interactive_exits(self):
        self._patch_io(interactive=False)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "config.yaml"
            with self.assertRaises(SystemExit):
                cli_setup.run_first_time_setup(target)

    def test_blank_exchange_fields_cancels(self):
        # 欄位全空 + 回車 = 取消；choose 第二次耗盡觸發結束，斷言未寫出設定
        self._patch_io(
            read_text=["123", "myhash", "", ""],
            choose=[0, None],
            asyncio_runs=[(True, "tg ok"), (True, "ex ok")],
        )
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "config.yaml"
            with self.assertRaises(StopIteration):
                cli_setup.run_first_time_setup(target)
            self.assertFalse(target.exists())


class TestStartupMenu(_Base):
    def test_enter_listens_without_change(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup.write_config") as wc, \
             mock.patch("autotrade.cli_setup.read_menu_key", return_value=b"\r"), \
             mock.patch("autotrade.cli_setup.is_interactive", return_value=True):
            cli_setup.prompt_startup_menu(p)
            wc.assert_not_called()

    def test_non_interactive_menu_returns(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup.write_config") as wc, \
             mock.patch("autotrade.cli_setup.read_menu_key") as rk, \
             mock.patch("autotrade.cli_setup.is_interactive", return_value=False):
            cli_setup.prompt_startup_menu(p)
            wc.assert_not_called()
            rk.assert_not_called()

    def test_menu_modify_tg(self):
        p = self._config_path(api_key="OLD", secret="OLD")
        with mock.patch("autotrade.cli_setup._remove_session"), \
             mock.patch("autotrade.cli_setup.asyncio.run", side_effect=_make_fake_run([(True, "ok")])), \
             mock.patch("autotrade.cli_setup.read_text",
                        side_effect=["456", "newhash"]):
            cli_setup._menu_modify_telegram(p)
        text = p.read_text(encoding="utf-8")
        self.assertIn("api_id: 456", text)
        self.assertIn("api_hash: newhash", text)
        self.assertIn("apiKey: OLD", text)  # 交易所段不變

    def test_menu_modify_tg_empty_cancels(self):
        p = self._config_path(api_key="OLD", secret="OLD")
        with mock.patch("autotrade.cli_setup.write_config") as wc, \
             mock.patch("autotrade.cli_setup.read_text", side_effect=["", ""]):
            cli_setup._menu_modify_telegram(p)
            wc.assert_not_called()

    def test_menu_modify_exchange_success(self):
        p = self._config_path(exchange="bybit", api_key="B", secret="S")
        with (mock.patch("autotrade.cli_setup.asyncio.run", side_effect=_make_fake_run([(True, "ok")])),
             mock.patch("autotrade.cli_setup.choose_from_list", return_value=2),  # bitget
             mock.patch("autotrade.cli_setup.read_text",
                        side_effect=["K2", "S2", "P2"])):  # apiKey/secret/passphrase
            cli_setup._menu_modify_exchange(p)
        cfg = load_config(str(p))
        self.assertEqual(cfg.exchanges["active"], "bitget")
        self.assertEqual(cfg.exchanges["bitget"]["apiKey"], "K2")
        self.assertEqual(cfg.exchanges["bitget"]["passphrase"], "P2")
        # 舊所 bybit 應被清空
        self.assertEqual(cfg.exchanges["bybit"]["apiKey"], "")

    def test_menu_modify_exchange_failure_no_write(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup.write_config") as wc, \
             mock.patch("autotrade.cli_setup.asyncio.run", side_effect=_make_fake_run([(False, "fail")])), \
             mock.patch("autotrade.cli_setup.choose_from_list", return_value=0), \
             mock.patch("autotrade.cli_setup.read_text", side_effect=["K", "S"]):
            cli_setup._menu_modify_exchange(p)
            wc.assert_not_called()

    def test_menu_modify_multiplier(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup.read_text", side_effect=["2.5"]):
            cli_setup._menu_modify_multiplier(p)
        from autotrade.multiplier_prompt import read_multiplier
        self.assertEqual(read_multiplier(p), 2.5)

    def test_menu_modify_multiplier_empty_keeps(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup.write_config") as wc, \
             mock.patch("autotrade.cli_setup.read_text", side_effect=[""]):
            cli_setup._menu_modify_multiplier(p)
            wc.assert_not_called()

    def test_menu_key_4_dispatches_tp_ratios(self):
        p = self._config_path()
        with mock.patch("autotrade.cli_setup._menu_modify_tp_ratios") as m, \
             mock.patch("autotrade.cli_setup.read_menu_key", return_value=b"4"), \
             mock.patch("autotrade.cli_setup.is_interactive", return_value=True):
            cli_setup.prompt_startup_menu(p)
            m.assert_called_once_with(p)

    def test_menu_modify_tp_ratios_saves(self):
        p = self._config_path()
        with mock.patch("autotrade.tp_ratios_prompt._read_text",
                        side_effect=["30", "70", "", ""]):
            cli_setup._menu_modify_tp_ratios(p)
        from autotrade.tp_ratios_prompt import read_tp_ratios
        self.assertEqual(read_tp_ratios(p), [30.0, 70.0, 0.0, 0.0])

    def test_menu_modify_tp_ratios_esc_cancels(self):
        p = self._config_path()
        with mock.patch("autotrade.tp_ratios_prompt._read_text",
                        side_effect=["30", None]) as rt, \
             mock.patch("autotrade.tp_ratios_prompt.save_tp_ratios") as sv:
            cli_setup._menu_modify_tp_ratios(p)
            sv.assert_not_called()

    def test_menu_modify_tp_ratios_all_empty_keeps(self):
        p = self._config_path()
        with mock.patch("autotrade.tp_ratios_prompt._read_text",
                        side_effect=["", "", "", ""]), \
             mock.patch("autotrade.tp_ratios_prompt.save_tp_ratios") as sv:
            cli_setup._menu_modify_tp_ratios(p)
            sv.assert_not_called()

    def test_menu_modify_tp_ratios_sum_mismatch_reprompts_then_saves(self):
        p = self._config_path()
        # 第一輪 10/20/30/30 加總 90 ≠ 100 → 重填 40/20/20/20 通過
        with mock.patch("autotrade.tp_ratios_prompt._read_text",
                        side_effect=["10", "20", "30", "30",
                                     "40", "20", "20", "20"]):
            cli_setup._menu_modify_tp_ratios(p)
        from autotrade.tp_ratios_prompt import read_tp_ratios
        self.assertEqual(read_tp_ratios(p), [40.0, 20.0, 20.0, 20.0])


if __name__ == "__main__":
    unittest.main()
