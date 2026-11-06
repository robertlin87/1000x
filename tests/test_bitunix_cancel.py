"""Bitunix 撤單：請求動詞、簽名動作、實際發出的動作三者必須一致。

BUG：底層只判斷「是不是提交類請求」，不是就一律用查詢發出去；
撤寫的是「刪除」卻被當成「查詢」，且簽名用刪除、實發查詢，交易所對不上。
本檔全程 mock HTTP，不觸網、不下真單。
"""
import unittest
from unittest.mock import MagicMock, patch

from autotrade.exchange.bitunix_rest import BitunixRestAdapter


def _response():
    r = MagicMock()
    r.json.return_value = {"code": 0, "data": {}}
    return r


class TestBitunixCancel(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        proxy_patch = patch(
            "autotrade.exchange.bitunix_rest.resolve_proxy", return_value=None
        )
        proxy_patch.start()
        self.addCleanup(proxy_patch.stop)
        self.adapter = BitunixRestAdapter("key", "secret")
        self.calls = {}
        for verb in ("get", "post", "delete"):
            p = patch(
                f"autotrade.exchange.bitunix_rest.requests.{verb}",
                return_value=_response(),
            )
            self.calls[verb] = p.start()
            self.addCleanup(p.stop)

    async def test_cancel_order_sends_delete_not_get(self):
        await self.adapter.cancel_order("oid-1", "BTCUSDT")
        self.calls["delete"].assert_called_once()
        self.calls["get"].assert_not_called()

    async def test_cancel_all_sends_delete_not_get(self):
        await self.adapter.cancel_all_for_symbol("BTCUSDT")
        self.calls["delete"].assert_called_once()
        self.calls["get"].assert_not_called()

    async def test_signed_method_matches_actual_verb(self):
        with patch.object(self.adapter, "_sign", wraps=self.adapter._sign) as sign:
            await self.adapter.cancel_order("oid-1", "BTCUSDT")
        self.assertEqual(sign.call_args.args[0], "DELETE")
        self.calls["delete"].assert_called_once()

    async def test_delete_has_no_json_body(self):
        # 參數在查詢串裡，請求體必須是空的；簽名與實發都要一致
        with patch.object(self.adapter, "_sign", wraps=self.adapter._sign) as sign:
            await self.adapter.cancel_order("oid-1", "BTCUSDT")
        self.assertEqual(sign.call_args.args[2], "")
        self.assertEqual(self.calls["delete"].call_args.kwargs["data"], "")

    async def test_cancel_keeps_order_id_in_query(self):
        await self.adapter.cancel_order("oid-1", "BTCUSDT")
        url = self.calls["delete"].call_args.args[0]
        self.assertIn("orderId=oid-1", url)

    async def test_get_still_uses_get(self):
        self.adapter._request("GET", "/api/v1/futures/account")
        self.calls["get"].assert_called_once()
        self.calls["delete"].assert_not_called()

    async def test_post_still_uses_post(self):
        self.adapter._request("POST", "/api/v1/futures/order", {"symbol": "BTCUSDT"})
        self.calls["post"].assert_called_once()
        self.calls["get"].assert_not_called()

    async def test_unknown_verb_is_rejected_not_silently_turned_into_get(self):
        with self.assertRaises(ValueError):
            self.adapter._request("PATCH", "/whatever")
        self.calls["get"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
