"""重启对账：DB 非终态持仓与交易所实态对齐，未处理事件重放。"""
from __future__ import annotations


class Reconciler:
    """TODO M3：启动时

    - DB 非终态 position vs 交易所 fetch_positions/fetch_open_orders
    - DB 有、交易所无 → CLOSED（人工平仓场景）
    - 交易所多余持仓 → UNKNOWN 记录并通知
    - signal_ops.processed=0 的事件重放
    """

    def __init__(self) -> None:
        raise NotImplementedError("M3")
