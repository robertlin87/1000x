"""觸發路由器。

主觸發（價格）= 交易所掛單成交，不依賴 TG；本層是備份核對與人為指令通道：
- 新報單（Signal）→ 查交易所實態 → 風控 validate → OrderManager.enter 建立主觸發掛單
- 新事件（signal_ops 新行）→ 備份核對/指令（動作前查交易所實態兜底，杜絕雙賣）

架構原則（與使用者確認 2026-11-04）：**交易所為唯一事實源**——風控的持倉列表、
事件的執行判斷都實時查交易所，不維護本地持倉狀態（重啟零成本）。
"""
from __future__ import annotations

import logging

from ..config import parse_multiplier
from ..risk.engine import validate
from ..risk.precision import calc_min_qty, round_down_qty

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
        """新報單：查交易所實態 → 風控 → 進場（主觸發通道建立）。"""
        try:
            market = await self._adapter.fetch_market(signal.symbol)
        except ValueError as e:
            await self._notifier.send(f"⚠️ 幣種不可交易，跳過：{signal.symbol}（{e}）")
            return

        contract_size = market["contractSize"]
        equity = await self._adapter.fetch_equity()
        open_positions = await self._adapter.fetch_all_positions()
        decision = validate(signal, equity, contract_size, open_positions,
                            self._risk_cfg, self._analysts_cfg)
        if not decision.accepted:
            await self._notifier.send(
                f"❌ 風控拒單 訂單{signal.order_id} {signal.symbol}：{decision.reason}"
            )
            return

        # 下單倍數（使用者設定，預設 1）：報單「控倉維持 x%」的 R 值縮放，
        # 手數 = floor(equity × R×倍數 ÷ |進場−止損| ÷ 合約倍數) 隨之縮放。
        # 只接受大於 0 的整數或小數（嚮導與 config.yaml 已校驗，此處兜底）
        try:
            multiplier = parse_multiplier(self._risk_cfg.get("order_multiplier", 1.0))
        except ValueError as e:
            await self._notifier.send(f"❌ 設定錯誤，跳過報單：{e}")
            return

        amount_step = market.get("precision", {}).get("amount")
        raw_qty = decision.qty * multiplier
        # 算出的手數按交易所要求的手數精度向下取整（不四捨五入），
        # 保證小數位合規、且不超過風控額度
        qty = round_down_qty(raw_qty, amount_step)

        # 手數上下限（使用者規則 2026-11-04，同日修正判斷閾值）：
        # - 交易所最低手數：amount.min 與交易所真實返回的 cost.min 折算取大者
        #   （交易所沒回傳 cost.min 時不再憑空用 5.0 兜底）
        # - 系統最低手數 = 交易所最低手數 × TP檔數 n，保證 n 檔 TP 每檔都能
        #   以交易所最低手數出場；倍數跟檔數走，不是固定 4
        # - 算出的手數（已按精度向下取整）只要 < 系統最低手數，就按系統最低手數下單
        # - 高於最高手數 → 按最高手數交易
        limits = market.get("limits", {})
        amount_limits = limits.get("amount") or {}
        n_tiers = max(1, len(signal.tps))
        exchange_min = 0.0
        if amount_limits.get("min"):
            exchange_min = max(exchange_min, float(amount_limits["min"]))
        cost_min = (limits.get("cost") or {}).get("min")
        if cost_min:
            exchange_min = max(
                exchange_min, calc_min_qty(signal.entry, amount_step, float(cost_min))
            )
        system_min = round_down_qty(exchange_min * n_tiers, amount_step)
        if system_min > 0 and qty < system_min:
            qty = system_min
            log.info("低於系統最低手數：按交易所最低手數 x%d 下單 qty=%s（交易所最低=%s）",
                     n_tiers, qty, exchange_min)
        max_qty = amount_limits.get("max")
        if max_qty and qty > float(max_qty):
            qty = round_down_qty(float(max_qty), amount_step)
            log.info("高於最高手數：按最高手數下單 qty=%s", qty)
        if qty <= 0:
            await self._notifier.send(
                f"⚠️ 手數按交易所精度取整後為 0，跳過：{signal.symbol}（原始 {raw_qty}）"
            )
            return
        log.info("下單倍數 x%s：風控手數 %s → 按步長 %s 向下取整後實際手數 %s",
                 multiplier, raw_qty, amount_step, qty)

        result = await self._om.enter(signal, qty)
        await self._notifier.send(
            f"✅ 已進場 訂單{signal.order_id} {signal.symbol} "
            f"{'做多' if signal.side == 'long' else '做空'} qty={result['qty']} SL={signal.sl}"
        )

    async def on_event(self, order_id: str, symbol: str | None, action_type: str,
                       tp_index: int | None = None, price: float | None = None,
                       mod_fields: dict | None = None, old_signal=None) -> None:
        """備份觸發：事件核對/指令（規則與使用者確認 2026-11-04）。

        - close / all_tp / sl_hit / hedge_exit：全平場景——平剩餘 + 撤該 symbol 掛單
          （all_tp/sl_hit 時倉位通常已被交易所平掉，close_all 會撤殘留掛單）
        - move_sl / hedge：amend SL 至 price（人為指令，雙通道任一出現即執行）
        - modify：跟隨分析師逐項修改（撤舊 TP 重掛新價、SL 變更 amend）
        - tp_hit：純信息（主觸發掛單已自動止盈，TP1-3 部分平倉不撤單）
        """
        if symbol is None:
            log.warning("事件缺 symbol，跳過執行：order=%s action=%s", order_id, action_type)
            return

        if action_type in ("close", "all_tp", "sl_hit", "hedge_exit"):
            closed = await self._om.close_all(symbol)
            await self._notifier.send(
                f"🟥 全平/撤單 {symbol}（{action_type}）"
                f"{'已執行' if closed else '無持倉僅記錄'}"
            )
        elif action_type in ("move_sl", "hedge") and price is not None:
            await self._om.amend_sl(symbol, price)
            await self._notifier.send(f"🔒 移動止損 {symbol} SL={price}")
        elif action_type == "modify" and mod_fields is not None:
            if old_signal is None:
                log.warning("訂單修改無歷史報單可對比，跳過執行：%s", order_id)
                return
            await self._om.apply_modify(
                symbol, old_signal.side,
                mod_fields, list(old_signal.tps), old_signal.sl,
            )
            await self._notifier.send(
                f"✏️ 已跟隨修改 {symbol}：{mod_fields.get('tps')} SL={mod_fields.get('sl')}"
            )
        elif action_type == "tp_hit":
            # 純信息：TP1-3 部分平倉，剩餘檔位掛單保留；編輯通道的補單核對待真實數據細化
            await self._notifier.send(f"🎯 TP{tp_index} 達成 {symbol} @{price}（信息，主觸發已止盈）")
        else:
            log.info("事件無需動作：order=%s action=%s", order_id, action_type)
