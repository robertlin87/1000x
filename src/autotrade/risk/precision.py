"""精度工具：張數/價格按交易所精度取整。

精度步長來自 exchange.fetch_market() 返回的 precision.amount / precision.price，
由 OrderManager 在掛單前對數量/價格做取整（Bybit 對精度不符會直接拒單）。
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_FLOOR


def round_down_qty(value: float, amount_step: float) -> float:
    """按手數精度步長向下取整（ROUND_DOWN），避免超買。

    用 Decimal 按十進制小數位計算：浮點算 6.576/0.001 得 6575.999999999999，
    math.floor 會砍成 6.575（少一檔、可能低於交易所最低手數）。
    """
    if not amount_step or amount_step <= 0:
        return value
    step = Decimal(str(amount_step))
    q = (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_FLOOR)
    return float(q * step)


def round_price(value: float, price_step: float) -> float:
    """按價格精度步長四捨五入到最近 tick。"""
    if not price_step or price_step <= 0:
        return value
    q = round(value / price_step)
    return round(q * price_step, 12)


def split_tier_qty(total_qty: float, n_tiers: int) -> list[float]:
    """TP 檔位手數均分：前 n-1 檔向下取整，末檔拿走全部剩餘。

    手數精度不能均分時的規則（使用者指定）：前 n-1 檔向下取整，最後一檔平掉全部剩餘。
    """
    if n_tiers <= 0 or total_qty <= 0:
        return []
    base = total_qty / n_tiers
    tiers = [base for _ in range(n_tiers - 1)]
    tiers.append(total_qty - sum(tiers))
    return tiers


def calc_min_qty(entry_price: float, amount_step: float, min_cost: float) -> float:
    """計算滿足交易所 min_cost（最小名義值）的最小下單手數。

    qty = ceil(min_cost / price / amount_step) * amount_step，按精度步長向上對齊。
    用於把交易所最小名義價值折算成手數下限，與 amount.min 取大者。
    """
    if not amount_step or amount_step <= 0:
        return 0.0
    if entry_price <= 0:
        return amount_step
    return round(math.ceil(min_cost / entry_price / amount_step) * amount_step, 12)
