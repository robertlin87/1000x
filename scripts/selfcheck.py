"""Bybit 真实下单自检：分阶段验证 adapter。

用法：
  python scripts/selfcheck.py --readonly   # 仅只读，不下单
  python scripts/selfcheck.py              # 只读 + 极小单交易验证（自动清理）
"""
import argparse
import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ccxt  # noqa: E402

from autotrade.config import load_config  # noqa: E402
from autotrade.exchange.base import NewOrder  # noqa: E402
from autotrade.exchange.factory import get_adapter  # noqa: E402


async def readonly(adapter) -> None:
    print("== fetch_equity ==")
    print("  equity =", await adapter.fetch_equity())
    print("== fetch_market LITUSDT ==")
    print("  ", await adapter.fetch_market("LITUSDT"))
    print("== fetch_position LITUSDT ==")
    print("  ", await adapter.fetch_position("LITUSDT"))
    print("== fetch_open_orders (全部) ==")
    print("  ", await adapter.fetch_open_orders())


async def _cleanup(adapter, sym: str) -> None:
    """撤掉该 symbol 全部挂单 + 市价平掉残余仓位（幂等，可反复调用）。"""
    await adapter.cancel_all_for_symbol(sym)
    pos = await adapter.fetch_position(sym)
    if pos and pos.get("qty", 0) > 0:
        side = "sell" if pos["side"] == "long" else "buy"
        o = NewOrder(symbol=sym, side=side, order_type="market",
                     qty=pos["qty"], reduce_only=True)
        await adapter.create_order(o)
        await asyncio.sleep(2)
    print("清理后持仓:", await adapter.fetch_position(sym))
    print("清理后挂单:", await adapter.fetch_open_orders(sym))


async def trade(adapter, cfg) -> None:
    b = cfg.exchanges["bybit"]
    proxy = cfg.exchanges.get("proxy") or {}
    purl = f"{proxy.get('type', 'http')}://{proxy.get('addr', '127.0.0.1')}:{proxy.get('port', 7897)}"
    raw = ccxt.bybit({
        "apiKey": b["apiKey"], "secret": b["secret"],
        "options": {"defaultType": "swap"},
        "proxies": {"http": purl, "https": purl},
    })
    raw.load_markets()
    sym = "LITUSDT"
    price = raw.fetch_ticker("LIT/USDT:USDT")["last"]
    print(f"\n== 交易自检（LITUSDT 现价 {price}）==")

    try:
        # 1) set_leverage
        await adapter.set_leverage(sym, 10)
        print("1) set_leverage(10) OK")

        # 2) 市价开最小手数单（约 5U 名义值），随单附 SL（下方 5%）
        market = await adapter.fetch_market(sym)
        min_amount = market["precision"]["amount"]
        min_cost = market["limits"]["cost"]["min"]
        qty = round(math.ceil(min_cost / price / min_amount) * min_amount, 6)
        sl = round(price * 0.95, 4)
        print(f"   最小手数 qty={qty}（约 {qty * price:.2f}U）")
        o = NewOrder(symbol=sym, side="buy", order_type="market", qty=qty,
                     sl_price=sl, leverage=10)
        oid = await adapter.create_order(o)
        print(f"2) 开仓市价单 id={oid} 附 SL={sl}")

        await asyncio.sleep(2)
        pos = await adapter.fetch_position(sym)
        print("   持仓:", pos)

        # 3) 挂 2 档 TP reduce-only 限价单（各半）
        tp1, tp2 = round(price * 1.02, 4), round(price * 1.04, 4)
        tier_qty = round(qty / 2, 6)
        for tp in (tp1, tp2):
            to = NewOrder(symbol=sym, side="sell", order_type="limit", qty=tier_qty,
                          price=tp, reduce_only=True)
            tid = await adapter.create_order(to)
            print(f"3) TP 单 id={tid} @ {tp} (reduce-only)")
        print("   挂单:", await adapter.fetch_open_orders(sym))

        # 4) 移动止损（trading-stop 端点）
        new_sl = round(price * 0.97, 4)
        await adapter.amend_order(order_id="", symbol=sym, sl_price=new_sl)
        print(f"4) 移动止损 -> SL={new_sl}")
        pos2 = await adapter.fetch_position(sym)
        print("   移损后持仓 sl_price:", pos2.get("sl_price") if pos2 else None)
    finally:
        print("\n== 清理 ==")
        await _cleanup(adapter, sym)
        print("交易自检完成，仓位与挂单已清理。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bybit 自检")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--readonly", action="store_true", help="仅只读验证，不下单")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ex = cfg.exchanges
    adapter = get_adapter(ex.get("active", "bybit"), ex.get("bybit", {}),
                          proxy=ex.get("proxy"))

    await readonly(adapter)
    if args.readonly:
        print("\n只读自检结束，未下单。")
        return
    await trade(adapter, cfg)


if __name__ == "__main__":
    asyncio.run(main())
