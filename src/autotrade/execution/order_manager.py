"""订单管理：进场（市价/限价 + SL/TP 挂载）、改单、撤单、终态清理。"""
from __future__ import annotations

import logging

from ..exchange.base import ExchangeAdapter, NewOrder
from ..risk.precision import round_down_qty, round_price, split_tier_qty

log = logging.getLogger("autotrade.execution.order_manager")


class OrderManager:
    """编排进场/平仓/移动止损，依赖 ExchangeAdapter 提供原子操作。

    - 进场：set_leverage → 开仓（随单附 SL）→ 挂 n 档 TP reduce-only 限价单
    - 终态：SL/最终 TP 触发、手工平仓 → 市价全平剩余 + cancel_all_for_symbol
    - 改单失败重试与降级市价平仓：由触发层（事件备份通道）负责，不在此处
    """

    def __init__(self, adapter: ExchangeAdapter) -> None:
        self._adapter = adapter

    async def enter(self, signal, qty: float) -> dict:
        """进场。signal 需含 symbol/side/is_limit/entry/sl/leverage/tps。"""
        sym = signal.symbol
        side = "buy" if signal.side == "long" else "sell"
        close_side = "sell" if side == "buy" else "buy"

        market = await self._adapter.fetch_market(sym)
        amount_step = market["precision"]["amount"]
        price_step = market["precision"]["price"]

        qty = round_down_qty(qty, amount_step)
        if qty <= 0:
            raise ValueError(f"手数取整后为 0：{sym}")

        await self._adapter.set_leverage(sym, signal.leverage)

        # 开仓：attached 随单附 SL（Bybit）；非 attached 开仓后独立挂 SL
        attached = bool(self._adapter.capabilities.get("supports_attached_sl"))
        order_type = "limit" if signal.is_limit else "market"
        entry_price = signal.entry if signal.is_limit else None
        entry_order = NewOrder(
            symbol=sym, side=side, order_type=order_type, qty=qty,
            price=entry_price, sl_price=signal.sl if attached else None,
            leverage=signal.leverage,
        )
        entry_id = await self._adapter.create_order(entry_order)
        log.info("开仓已提交：%s %s qty=%s id=%s", sym, side, qty, entry_id)
        if not attached:
            # 独立 SL（reduce-only 触发单，数量=当前持仓）
            await self._adapter.attach_sl_tp(entry_id, sym, signal.sl, None)

        # 挂 n 档 TP reduce-only 限价单（前 n-1 档 floor，末档=剩余）
        tps = signal.tps or []
        tp_ids: list[str] = []
        if tps:
            tiers = split_tier_qty(qty, len(tps))
            tier_qty = [round_down_qty(t, amount_step) for t in tiers]
            tier_qty[-1] = round(qty - sum(tier_qty[:-1]), 12)
            for price, tq in zip(tps, tier_qty):
                if tq <= 0:
                    continue
                tp_order = NewOrder(
                    symbol=sym, side=close_side, order_type="limit", qty=tq,
                    price=round_price(price, price_step), reduce_only=True,
                )
                tp_ids.append(await self._adapter.create_order(tp_order))
            log.info("已挂 %s 档 TP：%s", len(tp_ids), sym)

        return {"entry_order_id": entry_id, "tp_order_ids": tp_ids, "qty": qty}

    async def close_all(self, symbol: str) -> bool:
        """全平剩余 + 撤该 symbol 残留挂单（终态清理）。返回是否有持仓被平。

        全平场景（止盈末档/止损/手工平仓）后交易所可能残留 reduce-only 挂单：
        无持仓时若仍有残留挂单也必须撤（规则 2026-11-04）。TP1-3 部分平仓不调用本方法。
        """
        pos = await self._adapter.fetch_position(symbol)
        if pos and pos.get("qty", 0) > 0:
            close_side = "sell" if pos["side"] == "long" else "buy"
            order = NewOrder(
                symbol=symbol, side=close_side, order_type="market",
                qty=pos["qty"], reduce_only=True,
            )
            await self._adapter.create_order(order)
            log.info("已市价全平：%s（qty=%s）", symbol, pos["qty"])
            await self._adapter.cancel_all_for_symbol(symbol)
            return True
        # 无持仓：清理残留 reduce-only 挂单（全部止盈/止损后的残留）
        orders = await self._adapter.fetch_open_orders(symbol)
        leftovers = [o for o in orders if o.get("reduce_only")]
        if leftovers:
            await self._adapter.cancel_all_for_symbol(symbol)
            log.info("无持仓，已撤残留挂单：%s（%s 个 reduce-only）", symbol, len(leftovers))
        else:
            log.info("无持仓无挂单，跳过：%s", symbol)
        return False

    async def amend_sl(self, symbol: str, sl_price: float,
                       amount: float | None = None) -> None:
        """移动止损（自動移損/套保 → amend SL）。"""
        pos = await self._adapter.fetch_position(symbol)
        if not pos:
            log.warning("移动止损时无持仓：%s", symbol)
            return
        amt = amount if amount is not None else pos["qty"]
        await self._adapter.amend_order(order_id="", symbol=symbol,
                                        sl_price=sl_price, amount=amt)
        log.info("已移动止损：%s SL=%s", symbol, sl_price)

    async def apply_modify(self, symbol: str, side: str, mod_fields: dict,
                           old_tps: list[float], old_sl: float | None) -> None:
        """✏️ 訂單修改：跟随分析师逐项修改，只动变化项（规则 2026-11-04）。

        - 某档 TP 价格变了：撤旧档挂单、按新价重挂（数量 = 原档数量）
        - SL 变了：amend SL
        - 没变的档不动；旧挂单已不在（该档已成交）→ 跳过并告警，不重挂
        - 有效性守卫：新价必须仍在有效方向（做多高于现价/做空低于现价），
          防止重挂后立即成交、误平仓位
        """
        new_sl = mod_fields.get("sl")
        if new_sl is not None and old_sl is not None and abs(new_sl - old_sl) > 1e-12:
            await self.amend_sl(symbol, new_sl)

        last = await self._adapter.fetch_ticker(symbol)
        price_step = (await self._adapter.fetch_market(symbol))["precision"]["price"]
        open_orders = await self._adapter.fetch_open_orders(symbol)
        tp_orders = [o for o in open_orders
                     if o.get("reduce_only") and o.get("type") == "limit"]

        for idx, new_p in sorted(mod_fields.get("tps") or []):
            old_p = old_tps[idx - 1] if idx - 1 < len(old_tps) else None
            if old_p is not None and abs(new_p - old_p) < 1e-12:
                continue  # 未变化档不动
            if old_p is None:
                log.warning("新增 TP 档位无旧值可比，跳过：%s TP%s @%s", symbol, idx, new_p)
                continue
            # 撤旧档（按价格匹配挂单）
            replaced_qty = None
            for o in tp_orders:
                if o.get("price") is not None and abs(float(o["price"]) - old_p) < 1e-9:
                    await self._adapter.cancel_order(o["id"], symbol)
                    replaced_qty = float(o.get("qty") or 0)
                    break
            if replaced_qty is None:
                log.warning("旧档 TP%s 挂单已不在（可能已成交），跳过重挂：%s @%s",
                            idx, symbol, new_p)
                continue
            # 有效性守卫
            valid = (side == "long" and new_p > last) or (side == "short" and new_p < last)
            if not valid:
                log.warning("新 TP%s 价 %s 已越过现价 %s，跳过重挂：%s",
                            idx, new_p, last, symbol)
                continue
            close_side = "sell" if side == "long" else "buy"
            tp_order = NewOrder(
                symbol=symbol, side=close_side, order_type="limit", qty=replaced_qty,
                price=round_price(new_p, price_step), reduce_only=True,
            )
            await self._adapter.create_order(tp_order)
            log.info("已重挂 TP%s：%s @%s（qty=%s）", idx, symbol, new_p, replaced_qty)
