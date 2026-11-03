"""精度工具：张数/价格按交易所精度取整。

精度步长来自 exchange.fetch_market() 返回的 precision.amount / precision.price，
由 OrderManager 在挂单前对数量/价格做取整（Bybit 对精度不符会直接拒单）。
"""
from __future__ import annotations

import math


def round_down_qty(value: float, amount_step: float) -> float:
    """按手数精度步长向下取整（ROUND_DOWN），避免超买。"""
    if not amount_step or amount_step <= 0:
        return value
    q = math.floor(value / amount_step)
    return round(q * amount_step, 12)  # 消除浮点尾差


def round_price(value: float, price_step: float) -> float:
    """按价格精度步长四舍五入到最近 tick。"""
    if not price_step or price_step <= 0:
        return value
    q = round(value / price_step)
    return round(q * price_step, 12)


def split_tier_qty(total_qty: float, n_tiers: int) -> list[float]:
    """TP 档位手数均分：前 n-1 档向下取整，末档拿走全部剩余。

    手数精度不能均分时的规则（用户指定）：前 n-1 档向下取整，最后一档平掉全部剩余。
    """
    if n_tiers <= 0 or total_qty <= 0:
        return []
    base = total_qty / n_tiers
    tiers = [base for _ in range(n_tiers - 1)]
    tiers.append(total_qty - sum(tiers))
    return tiers


def calc_min_qty(entry_price: float, amount_step: float, min_cost: float) -> float:
    """计算满足交易所 min_cost（最小名义值）的最小下单手数。

    qty = ceil(min_cost / price / amount_step) * amount_step，按精度步长向上对齐。
    用于试运行：每笔强制下最小手数，忽略报单风控 R% 算出的手数。
    """
    if not amount_step or amount_step <= 0:
        return 0.0
    if entry_price <= 0:
        return amount_step
    return round(math.ceil(min_cost / entry_price / amount_step) * amount_step, 12)
