"""重啟對賬：DB 非終態持倉與交易所實態對齊，未處理事件重放。"""
from __future__ import annotations


class Reconciler:
    """TODO M3：啟動時

    - DB 非終態 position vs 交易所 fetch_positions/fetch_open_orders
    - DB 有、交易所無 → CLOSED（人工平倉場景）
    - 交易所多餘持倉 → UNKNOWN 記錄並通知
    - signal_ops.processed=0 的事件重放
    """

    def __init__(self) -> None:
        raise NotImplementedError("M3")
