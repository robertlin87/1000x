"""风控引擎。

手数公式（用户指定）：
    张数 = equity × R% ÷ |建仓价 − 止损价| ÷ 合约倍数
R% = 报单「控仓维持 x% 风控」的 x；合约倍数 = 各交易所每张合约的币数
（ccxt market['contractSize']，各所不同）；向下取整到整数张。
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
    """按 R% 风控与止损距离计算合约张数（向下取整）。"""
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
    """保证金复算校验：margin_pct ≈ risk_pct / (stop_dist_pct × leverage)。

    三条真实样例均吻合（订单216：7.61 ≈ 2.00/(2.63×10)=7.60）。超差说明
    信号有误或模板误配，应 reject。
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
    """M2 风控校验，返回 RiskDecision(accepted, reason, qty)。

    依次检查：
      1. 分析师白名单（allow_all=false 时生效）
      2. 同 symbol 反向信号拒单
      3. 并发持仓上限（按不同 symbol 数计）
      4. 保证金复算校验（复用 check_margin_formula）
      5. 手数 = calc_contract_qty + minNotional（名义值下限）
      6. 日亏上限（daily_pnl 负值超过阈值则拒）

    手数公式与保证金复算已实现并有测试，此处直接复用。
    open_positions 元素需含 symbol 与 side（"long"/"short"）。
    """
    risk_cfg = risk_cfg or {}
    analysts_cfg = analysts_cfg or {}
    open_positions = open_positions or []

    # 1) 分析师白名单
    if not analysts_cfg.get("allow_all", True):
        allow = analysts_cfg.get("list", [])
        if signal.analyst not in allow:
            return RiskDecision(False, f"分析师不在白名单：{signal.analyst}")

    # 2) 同 symbol 反向信号
    for pos in open_positions:
        if pos.get("symbol") == signal.symbol and pos.get("side") != signal.side:
            return RiskDecision(False, f"同 symbol 反向信号拒单：{signal.symbol}")

    # 3) 并发持仓上限（按不同 symbol 数计）
    max_pos = int(risk_cfg.get("max_concurrent_positions", 3))
    held_symbols = {pos.get("symbol") for pos in open_positions}
    if signal.symbol not in held_symbols and len(held_symbols) >= max_pos:
        return RiskDecision(False, f"并发持仓达上限 {max_pos}")

    # 4) 保证金复算校验
    tol = float(risk_cfg.get("margin_formula_tol_pct", 0.1))
    if not check_margin_formula(
        signal.margin_pct, signal.risk_pct, signal.stop_dist_pct, signal.leverage, tol
    ):
        return RiskDecision(False, "保证金复算超差")

    # 5) 手数 + minNotional
    qty = calc_contract_qty(equity, signal.risk_pct, signal.entry, signal.sl, contract_size)
    if qty <= 0:
        return RiskDecision(False, "手数计算为 0（风控金额或价差异常）")
    min_notional = float(risk_cfg.get("min_notional", 5.0))
    notional = qty * contract_size * signal.entry
    if notional < min_notional:
        return RiskDecision(False, f"名义值过小：{notional:.2f} < {min_notional}")

    # 6) 日亏上限
    daily_loss_pct = float(risk_cfg.get("daily_loss_pct", 5.0))
    if daily_pnl < 0 and abs(daily_pnl) >= equity * daily_loss_pct / 100.0:
        return RiskDecision(False, "当日亏损已达上限")

    return RiskDecision(True, "", qty)
