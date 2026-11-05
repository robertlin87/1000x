"""風控引擎。

手數公式（使用者指定）：
    張數 = equity × R% ÷ |建倉價 − 止損價| ÷ 合約倍數
R% = 報單「控倉維持 x% 風控」的 x；合約倍數 = 各交易所每張合約的幣數
（ccxt market['contractSize']，各所不同）；向下取整到整數張。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def calc_contract_qty(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    contract_size: float,
) -> int:
    """按 R% 風控與止損距離計算合約張數（向下取整）。"""
    if contract_size <= 0 or entry == stop:
        return 0
    coins = equity * (risk_pct / 100.0) / abs(entry - stop)
    return math.floor(coins / contract_size)


def check_margin_formula(
    margin_pct: float,
    risk_pct: float,
    stop_dist_pct: float,
    leverage: int,
    tol_pct: float = 0.1,
) -> bool:
    """保證金復算校驗：margin_pct ≈ risk_pct / (stop_dist_pct × leverage)。

    三條真實樣例均吻合（訂單216：7.61 ≈ 2.00/(2.63×10)=7.60）。超差說明
    信號有誤或模板誤配，應 reject。
    """
    if stop_dist_pct <= 0 or leverage <= 0:
        return False
    expected = risk_pct / (stop_dist_pct * leverage) * 100.0
    return abs(margin_pct - expected) <= tol_pct


@dataclass(slots=True)
class RiskDecision:
    accepted: bool
    reason: str = ""
    qty: int = 0


def validate(
    signal,
    equity: float,
    contract_size: float,
    open_positions: list | None = None,
    risk_cfg: dict | None = None,
    analysts_cfg: dict | None = None,
    daily_pnl: float = 0.0,
) -> RiskDecision:
    """M2 風控校驗，返回 RiskDecision(accepted, reason, qty)。

    依次檢查：
      1. 分析師白名單（allow_all=false 時生效）
      2. 同 symbol 反向信號拒單
      3. 併發持倉上限（按不同 symbol 數計）
      4. 保證金復算校驗（複用 check_margin_formula）
      5. 手數 = calc_contract_qty + minNotional（名義值下限）
      6. 日虧上限（daily_pnl 負值超過閾值則拒）

    手數公式與保證金復算已實現並有測試，此處直接複用。
    open_positions 元素需含 symbol 與 side（"long"/"short"）。
    """
    risk_cfg = risk_cfg or {}
    analysts_cfg = analysts_cfg or {}
    open_positions = open_positions or []

    # 1) 分析師白名單
    if not analysts_cfg.get("allow_all", True):
        allow = analysts_cfg.get("list", [])
        if signal.analyst not in allow:
            return RiskDecision(False, f"分析師不在白名單：{signal.analyst}")

    # 2) 同 symbol 反向信號
    for pos in open_positions:
        if pos.get("symbol") == signal.symbol and pos.get("side") != signal.side:
            return RiskDecision(False, f"同 symbol 反向信號拒單：{signal.symbol}")

    # 3) 併發持倉上限（按不同 symbol 數計）
    max_pos = int(risk_cfg.get("max_concurrent_positions", 3))
    held_symbols = {pos.get("symbol") for pos in open_positions}
    if signal.symbol not in held_symbols and len(held_symbols) >= max_pos:
        return RiskDecision(False, f"併發持倉達上限 {max_pos}")

    # 4) 保證金復算校驗
    tol = float(risk_cfg.get("margin_formula_tol_pct", 0.1))
    if not check_margin_formula(
        signal.margin_pct, signal.risk_pct, signal.stop_dist_pct, signal.leverage, tol
    ):
        return RiskDecision(False, "保證金復算超差")

    # 5) 手數 + minNotional
    qty = calc_contract_qty(equity, signal.risk_pct, signal.entry, signal.sl, contract_size)
    # qty=0 不再在這裡拒單：按使用者規則「手數低於系統最低手數就按系統最低手數
    # 下單」，0 也屬於低於，交給 TriggerRouter 的 system_min 託底。
    # 若交易所沒給任何下限（system_min 也是 0），執行層會跳過下單並告警。
    if qty > 0:
        min_notional = float(risk_cfg.get("min_notional", 5.0))
        notional = qty * contract_size * signal.entry
        if notional < min_notional:
            return RiskDecision(False, f"名義值過小：{notional:.2f} < {min_notional}")

    # 6) 日虧上限
    daily_loss_pct = float(risk_cfg.get("daily_loss_pct", 5.0))
    if daily_pnl < 0 and abs(daily_pnl) >= equity * daily_loss_pct / 100.0:
        return RiskDecision(False, "當日虧損已達上限")

    return RiskDecision(True, "", qty)
