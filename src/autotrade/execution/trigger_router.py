"""触发路由器。

主触发（价格）= 交易所挂单成交，不依赖 TG；本层是备份核对与人为指令通道：
- 新报单（Signal）→ 查交易所实态 → 风控 validate → OrderManager.enter 建立主触发挂单
- 新事件（signal_ops 新行）→ 备份核对/指令（动作前查交易所实态兜底，杜绝双卖）

架构原则（与用户确认 2026-11-04）：**交易所为唯一事实源**——风控的持仓列表、
事件的执行判断都实时查交易所，不维护本地持仓状态（重启零成本）。
"""
from __future__ import annotations

import logging

from ..risk.engine import validate
from ..risk.precision import calc_min_qty

log = logging.getLogger("autotrade.execution.trigger_router")


class TriggerRouter:
    def __init__(self, adapter, order_manager, notifier,
                 risk_cfg: dict | None = None, analysts_cfg: dict | None = None) -> None:
        self._adapter = adapter
        self._om = order_manager
        self._notifier = notifier
        self._risk_cfg = risk_cfg or {}
        self._analysts_cfg = analysts_cfg or {}

    async def on_signal(self, signal) -> None:
        """新报单：查交易所实态 → 风控 → 进场（主触发通道建立）。"""
        try:
            market = await self._adapter.fetch_market(signal.symbol)
        except ValueError as e:
            await self._notifier.send(f"⚠️ 币种不可交易，跳过：{signal.symbol}（{e}）")
            return

        contract_size = market["contractSize"]
        equity = await self._adapter.fetch_equity()
        open_positions = await self._adapter.fetch_all_positions()
        decision = validate(signal, equity, contract_size, open_positions,
                            self._risk_cfg, self._analysts_cfg)
        if not decision.accepted:
            await self._notifier.send(
                f"❌ 风控拒单 订单{signal.order_id} {signal.symbol}：{decision.reason}"
            )
            return

        # 下单倍数（用户设定，默认 1）：报单「控仓维持 x%」的 R 值缩放，
        # 手数 = floor(equity × R×倍数 ÷ |进場−止損| ÷ 合约倍数) 随之缩放
        multiplier = float(self._risk_cfg.get("order_multiplier", 1.0))
        qty = round(decision.qty * multiplier, 12)

        # 手数上下限（用户规则 2026-11-04）：
        # - 低于最低手数 → 按最低手数 × TP档数 交易（保证每档都能以最小手数出场）
        # - 高于最高手数 → 按最高手数交易
        limits = market.get("limits", {})
        amount_limits = limits.get("amount") or {}
        amount_step = market.get("precision", {}).get("amount")
        min_cost = (limits.get("cost") or {}).get("min") or 5.0
        eff_min = calc_min_qty(signal.entry, amount_step, min_cost)
        if amount_limits.get("min"):
            eff_min = max(eff_min, float(amount_limits["min"]))
        n_tiers = max(1, len(signal.tps))
        if qty < eff_min:
            qty = round(eff_min * n_tiers, 12)
            log.info("低于最低手数：按最低手数 x%d 下单 qty=%s（最低=%s）",
                     n_tiers, qty, eff_min)
        max_qty = amount_limits.get("max")
        if max_qty and qty > float(max_qty):
            qty = float(max_qty)
            log.info("高于最高手数：按最高手数下单 qty=%s", qty)
        log.info("下单倍数 x%s：风控手数 %s → 实际手数 %s",
                 multiplier, decision.qty, qty)

        result = await self._om.enter(signal, qty)
        await self._notifier.send(
            f"✅ 已进场 订单{signal.order_id} {signal.symbol} "
            f"{'做多' if signal.side == 'long' else '做空'} qty={result['qty']} SL={signal.sl}"
        )

    async def on_event(self, order_id: str, symbol: str | None, action_type: str,
                       tp_index: int | None = None, price: float | None = None,
                       mod_fields: dict | None = None, old_signal=None) -> None:
        """备份触发：事件核对/指令（规则与用户确认 2026-11-04）。

        - close / all_tp / sl_hit / hedge_exit：全平场景——平剩余 + 撤该 symbol 挂单
          （all_tp/sl_hit 时仓位通常已被交易所平掉，close_all 会撤残留挂单）
        - move_sl / hedge：amend SL 至 price（人为指令，双通道任一出现即执行）
        - modify：跟随分析师逐项修改（撤旧 TP 重挂新价、SL 变更 amend）
        - tp_hit：纯信息（主触发挂单已自动止盈，TP1-3 部分平仓不撤单）
        """
        if symbol is None:
            log.warning("事件缺 symbol，跳过执行：order=%s action=%s", order_id, action_type)
            return

        if action_type in ("close", "all_tp", "sl_hit", "hedge_exit"):
            closed = await self._om.close_all(symbol)
            await self._notifier.send(
                f"🟥 全平/撤单 {symbol}（{action_type}）"
                f"{'已执行' if closed else '无持仓仅记录'}"
            )
        elif action_type in ("move_sl", "hedge") and price is not None:
            await self._om.amend_sl(symbol, price)
            await self._notifier.send(f"🔒 移动止损 {symbol} SL={price}")
        elif action_type == "modify" and mod_fields is not None:
            if old_signal is None:
                log.warning("訂單修改无历史报单可对比，跳过执行：%s", order_id)
                return
            await self._om.apply_modify(
                symbol, old_signal.side,
                mod_fields, list(old_signal.tps), old_signal.sl,
            )
            await self._notifier.send(
                f"✏️ 已跟随修改 {symbol}：{mod_fields.get('tps')} SL={mod_fields.get('sl')}"
            )
        elif action_type == "tp_hit":
            # 纯信息：TP1-3 部分平仓，剩余档位挂单保留；编辑通道的补单核对待真实数据细化
            await self._notifier.send(f"🎯 TP{tp_index} 达成 {symbol} @{price}（信息，主触发已止盈）")
        else:
            log.info("事件无需动作：order=%s action=%s", order_id, action_type)
