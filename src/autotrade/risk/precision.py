"""精度工具：張數/價格按交易所精度取整。

精度步長來自 exchange.fetch_market() 返回的 precision.amount / precision.price，
由 OrderManager 在掛單前對數量/價格做取整（Bybit 對精度不符會直接拒單）。
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal, ROUND_FLOOR

log = logging.getLogger("autotrade.risk.precision")


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


def split_tier_qty(
    total_qty: float,
    n_tiers: int,
    ratios: list[float] | None = None,
) -> list[float]:
    """TP 檔位手數劃分。

    ratios=None → 均分（原行為）：前 n-1 檔均分，末檔拿走全部剩餘。
    給定百分比（0~100 的數字，合計 ≈ 100）→ 前 n-1 檔按比例，末檔=全部剩餘。
    加總不在此校驗（末檔 sweep 兜底）；結構性不可用（長度不足/全 0/非有限值）
    回退均分。
    """
    if n_tiers <= 0 or total_qty <= 0:
        return []
    if ratios is None:
        base = total_qty / n_tiers
        tiers = [base for _ in range(n_tiers - 1)]
        tiers.append(total_qty - sum(tiers))
        return tiers
    used = list(ratios[:n_tiers])
    if len(used) < n_tiers or sum(used) <= 0 or not all(
        math.isfinite(p) and p >= 0 for p in used
    ):
        return split_tier_qty(total_qty, n_tiers)
    tiers = [total_qty * p / 100.0 for p in used[:-1]]
    tiers.append(total_qty - sum(tiers))
    return tiers


def exchange_min_qty(market: dict, entry_price: float) -> float:
    """交易所最低手數：amount.min 與 cost.min 折算取大者；均缺失返回 0。

    cost.min 是名義值下限（USDT），按進場價折算成手數下限後與 amount.min 取大
    （使用者規則 2026-11-04：交易所沒返回 cost.min 時不憑空兜底）。
    原 TriggerRouter 內聯邏輯抽為公共函數，plan_tp_tiers 共用。
    """
    limits = market.get("limits") or {}
    amount_min = (limits.get("amount") or {}).get("min")
    cost_min = (limits.get("cost") or {}).get("min")
    exchange_min = 0.0
    if amount_min:
        exchange_min = max(exchange_min, float(amount_min))
    if cost_min:
        amount_step = (market.get("precision") or {}).get("amount")
        exchange_min = max(
            exchange_min, calc_min_qty(entry_price, amount_step, float(cost_min))
        )
    return exchange_min


def last_positive_tier(ratios: list[float] | None) -> int:
    """比例中最後一個 >0 的下標（1-indexed）；None 或全 0 返回 0。

    全平檔位 = 用戶填寫的實際最後一個非 0 檔位（與報單檔數取小者）。
    """
    if not ratios:
        return 0
    idx = 0
    for i, p in enumerate(ratios, 1):
        if p > 0:
            idx = i
    return idx


def plan_tp_tiers(
    total_qty: float,
    tps: list[float],
    ratios: list[float] | None,
    amount_step: float,
    exchange_min: float,
) -> list[tuple[float, float]]:
    """計算實際 TP 掛單 (price, qty) 清單——生產路徑唯一規劃入口。

    規則（使用者 2026-11-05 逐例確認）：
    - 全平檔位 = 用戶比例中最後一個非 0 檔與報單最後一檔取靠前者：
      n = min(len(tps), last_positive_tier(ratios))；ratios 全 0（理論不可達）回退
      均分且 n 以 4 為上限
    - 前 n-1 檔：qty×pct/100 按 amount_step 向下取整；0 或低於交易所最低手數
      不掛、份額流入末檔
    - 末檔 sweep = total_qty − 已掛合計，在 tps[n-1] 價格全清剩餘
    - 報單多出的檔位（含第 5 檔起）不掛任何單
    - 末檔本身低於交易所最低手數 → 併入最後已掛檔（該檔成實際末檔）；
      無已掛檔可併 → 跳過並告警（持倉仍有 SL 保護；生產路徑經 router 的
      system_min 托底後不可達）

    數學不變量：total_qty 已按 step 對齊 → 每檔 floor 後是 step 整數倍 →
    sweep 無漂移、Σ實掛恰 = total_qty、reduce-only 不超持倉。
    """
    n_user = last_positive_tier(ratios)
    if ratios is None:
        n = min(len(tps), 4)  # 均分（向後兼容），上限 4 檔
    elif n_user > 0:
        n = min(len(tps), n_user)
    else:
        n = min(len(tps), 4)  # 全 0 防禦性回退：均分且上限 4 檔
        log.warning("止盈部位比例全為 0，防禦性回退均分掛單")
    if n <= 0 or total_qty <= 0 or not tps:
        return []
    if len(tps) > n:
        log.warning("報單 %s 檔，超過實際掛檔數 %s，多餘檔位不掛單", len(tps), n)

    raw = split_tier_qty(total_qty, n, ratios)
    plans: list[tuple[float, float]] = []
    placed = 0.0
    for i in range(n - 1):
        tq = round_down_qty(raw[i], amount_step)
        if tq <= 0:
            continue
        if exchange_min > 0 and tq < exchange_min:
            log.warning("TP%s 手數 %s 低於交易所最低手數 %s，併入末檔",
                        i + 1, tq, exchange_min)
            continue
        plans.append((tps[i], tq))
        placed += tq
    sweep = round(total_qty - placed, 12)
    if sweep > 0:
        if exchange_min > 0 and sweep < exchange_min:
            if plans:
                p, q = plans[-1]
                plans[-1] = (p, q + sweep)
                log.warning("末檔手數 %s 低於交易所最低手數，併入上一檔", sweep)
            else:
                log.warning("末檔手數 %s 低於交易所最低手數且無可併入的檔位，跳過掛單", sweep)
        else:
            plans.append((tps[n - 1], sweep))
    return plans


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
