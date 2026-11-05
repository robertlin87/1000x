"""交易所自檢：逐家驗證適配器（readonly + 真實小單全路徑，自動清理）。

用法：
  python scripts/selfcheck.py --readonly                       # 僅只讀（用 config 的 active）
  python scripts/selfcheck.py --exchange binance --readonly    # 指定交易所只讀
  python scripts/selfcheck.py --exchange binance               # 真實小單全路徑驗證（自動清理）
  python scripts/selfcheck.py --exchange bitget --symbol LITUSDT

全路徑：set_leverage → 開倉（附/掛 SL）→ 掛 TP 檔 → 移動止損 → 全平清理。
按 capabilities 自動走 attached / 獨立 SL 兩條路徑（與生產 OrderManager 一致）。
"""
import argparse
import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autotrade.config import load_config  # noqa: E402
from autotrade.exchange.factory import get_adapter  # noqa: E402
from autotrade.execution.order_manager import OrderManager  # noqa: E402
from autotrade.parser.entry_parser import Signal  # noqa: E402
from autotrade.risk.precision import round_price  # noqa: E402


async def readonly(adapter) -> None:
    print("== fetch_equity ==")
    print("  equity =", await adapter.fetch_equity())
    print("== fetch_market LITUSDT ==")
    try:
        print("  ", await adapter.fetch_market("LITUSDT"))
    except ValueError as e:
        print("  ", e)
    print("== fetch_all_positions ==")
    print("  ", await adapter.fetch_all_positions())
    print("== fetch_open_orders (全部) ==")
    print("  ", await adapter.fetch_open_orders())


async def trade(adapter, symbol: str) -> None:
    """真實小單全路徑驗證，走生產同款 OrderManager 流程，結束自動清理。"""
    market = await adapter.fetch_market(symbol)
    price = await adapter.fetch_ticker(symbol)
    print(f"\n== 交易自檢（{symbol} 現價 {price}）==")

    amount_step = market["precision"]["amount"]
    price_step = market["precision"]["price"]
    min_cost = (market.get("limits", {}).get("cost") or {}).get("min") or 5.0
    if not amount_step or price <= 0:
        print("  市場精度缺失，跳過交易自檢")
        return
    min_qty = math.ceil(min_cost / price / amount_step) * amount_step
    qty = round(min_qty * 2, 12)  # 2 檔 TP 各最小手數
    sl = round_price(price * 0.95, price_step)
    tps = [round_price(price * 1.02, price_step), round_price(price * 1.04, price_step)]

    sig = Signal(order_id="selfcheck", symbol=symbol, side="long", entry=price,
                 is_limit=False, leverage=10, sl=sl, tps=tps,
                 margin_pct=10.0, risk_pct=2.0, stop_dist_pct=5.0, analyst="selfcheck")
    om = OrderManager(adapter)
    try:
        result = await om.enter(sig, qty)
        print("1) 開倉+SL+TP 完成:", result)
        await asyncio.sleep(2)
        print("   持倉:", await adapter.fetch_position(symbol))
        print("   掛單:", await adapter.fetch_open_orders(symbol))

        new_sl = round_price(price * 0.97, price_step)
        await om.amend_sl(symbol, new_sl)
        print(f"2) 移動止損 -> SL={new_sl}")
        pos = await adapter.fetch_position(symbol)
        print("   移損後持倉 sl_price:", pos.get("sl_price") if pos else None)
    finally:
        print("\n== 清理 ==")
        await om.close_all(symbol)
        await asyncio.sleep(2)
        print("清理後持倉:", await adapter.fetch_position(symbol))
        print("清理後掛單:", await adapter.fetch_open_orders(symbol))
        print("交易自檢完成，倉位與掛單已清理。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="交易所自檢")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--exchange", default=None, help="覆蓋 config 的 exchanges.active")
    parser.add_argument("--symbol", default="LITUSDT", help="交易自檢用的交易對")
    parser.add_argument("--readonly", action="store_true", help="僅只讀驗證，不下單")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ex = cfg.exchanges
    name = args.exchange or ex.get("active", "bybit")
    print(f"== 交易所：{name} ==")
    adapter = get_adapter(name, ex.get(name, {}), proxy=ex.get("proxy"))

    await readonly(adapter)
    if args.readonly:
        print("\n只讀自檢結束，未下單。")
        return
    await trade(adapter, args.symbol)


if __name__ == "__main__":
    asyncio.run(main())
