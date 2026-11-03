"""操作記錄行解析器：解析编辑消息追加的操作行，供统一事件层差量比对。

幂等键 op_line_hash 按语义归一（action_type|tp_index|price）——同一操作
经编辑行与新消息通知两通道出现时算同一事件，UNIQUE 约束下只触发一次。
✏️ 訂單修改是特殊的多行块（修改行后跟 進場/TPn/止損 字段行），用
modify_hash 按内容+时间戳归一，两通道同一次修改只触发一次。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "config" / "templates"

_TS_RE = re.compile(r"\((\d{4}-\d{2}-\d{2}\s[\d:]+)\)")
_ARROW_RE = re.compile(r"^\s*[→➜]\s*")

# 訂單修改块的紧凑字段行（无冒号）：進場 X / TPn X / 止損 X
_ENTRY_MOD_RE = re.compile(r"進場\s+(?P<v>[\d.,]+)")
_TP_MOD_RE = re.compile(r"TP(?P<i>[1-4])\s+(?P<v>[\d.,]+)")
_SL_MOD_RE = re.compile(r"止損\s+(?P<v>[\d.,]+)")


@dataclass(slots=True)
class OpLine:
    action_type: str        # tp_hit|all_tp|move_sl|hedge|hedge_exit|close|sl_hit|modify|ignore|unknown
    tp_index: int | None = None
    price: float | None = None
    line_text: str = ""
    ts_text: str = ""
    mod_fields: dict | None = None   # modify：{"entry": float|None, "tps": [(idx, price)], "sl": float|None}


def op_line_hash(
    action_type: str,
    tp_index: int | None,
    price: float | None,
    line_text: str = "",
) -> str:
    """统一事件层幂等键：编辑行与新消息通知跨通道去重。

    已知类型按 (action_type, tp_index, price) 归一——两通道价格表示
    若因舍入不同会视为两个事件，执行层动作前会再查交易所实态兜底。
    unknown 行按原文，保证模板补齐所需信息不丢。
    """
    if action_type == "unknown":
        key = f"unknown|{line_text}"
    else:
        key = f"{action_type}|{tp_index or ''}|{price or ''}"
    return hashlib.sha1(key.encode()).hexdigest()


def modify_hash(fields: dict | None, ts_text: str = "") -> str:
    """訂單修改事件的幂等键：按内容+时间戳归一，两通道同一次修改只触发一次。

    不同时间戳的不同修改是不同事件；同一次修改（编辑块与紧凑通知）键相同。
    """
    fields = fields or {}
    tps = "|".join(f"{i}:{p}" for i, p in sorted(fields.get("tps") or []))
    key = f"modify|{fields.get('entry')}|{tps}|{fields.get('sl')}|{ts_text}"
    return hashlib.sha1(key.encode()).hexdigest()


def parse_modify_fields(text: str) -> dict:
    """从文本里提取訂單修改的紧凑字段（進場/TPn/止損，无冒号格式）。

    返回 {"entry": float|None, "tps": [(idx, price)...], "sl": float|None}。
    同一文本可含多个字段（紧凑通知用「·」分隔，编辑块逐行累加）。
    """
    entry = None
    m = _ENTRY_MOD_RE.search(text)
    if m:
        entry = float(m.group("v").replace(",", ""))
    tps = sorted(
        (int(tm.group("i")), float(tm.group("v").replace(",", "")))
        for tm in _TP_MOD_RE.finditer(text)
    )
    sl = None
    m = _SL_MOD_RE.search(text)
    if m:
        sl = float(m.group("v").replace(",", ""))
    return {"entry": entry, "tps": tps, "sl": sl}


def _merge_fields(base: dict, extra: dict) -> dict:
    if base.get("entry") is None:
        base["entry"] = extra.get("entry")
    if base.get("sl") is None:
        base["sl"] = extra.get("sl")
    known = {i for i, _ in base.get("tps") or []}
    for i, p in extra.get("tps") or []:
        if i not in known:
            base.setdefault("tps", []).append((i, p))
    return base


def _extract_ts(line: str) -> str:
    m = _TS_RE.search(line)
    return m.group(1) if m else ""


class OpParser:
    """按 ops_header 切出「操作記錄」段，逐行匹配 op_lines.yaml。

    容忍行尾时间戳与「（TP1 後）」注记；✏️ 訂單修改为多行块（修改行后
    跟 進場/TPn/止損 字段行）；未匹配行返回 action_type=unknown 供模板
    补齐；💬 行为 ignore。
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        path = (templates_dir or TEMPLATES_DIR) / "op_lines.yaml"
        with open(path, encoding="utf-8") as f:
            tpl = _yaml.load(f)
        self._ops_header = re.compile(tpl["ops_header"])
        self._templates = [
            (t["action_type"], re.compile(t["regex"])) for t in tpl["templates"]
        ]

    def extract_ops(self, text: str) -> list[OpLine]:
        parts = self._ops_header.split(text, maxsplit=1)
        if len(parts) < 2:
            return []
        lines = parts[1].splitlines()
        out: list[OpLine] = []
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            i += 1
            line = raw_line.strip()
            if not line:
                continue
            # 💬 分析师备注：忽略（先于模板判断，防止备注内容误命中「平倉」等词）
            if line.startswith("💬"):
                out.append(OpLine(action_type="ignore", line_text=raw_line))
                continue
            line = _ARROW_RE.sub("", line)
            if not line:
                continue
            matched = False
            for action_type, rx in self._templates:
                m = rx.search(line)
                if not m:
                    continue
                if action_type == "modify":
                    op, consumed = self._parse_modify_block(raw_line, line, lines, i)
                    out.append(op)
                    i += consumed
                else:
                    g = m.groupdict()
                    out.append(OpLine(
                        action_type=action_type,
                        tp_index=int(g["tp_index"]) if g.get("tp_index") else None,
                        price=float(g["price"].replace(",", "")) if g.get("price") else None,
                        line_text=raw_line,
                        ts_text=_extract_ts(raw_line),
                    ))
                matched = True
                break
            if not matched:
                out.append(OpLine(
                    action_type="unknown",
                    line_text=raw_line,
                    ts_text=_extract_ts(raw_line),
                ))
        return out

    def _parse_modify_block(self, raw_line: str, line: str, lines: list[str],
                            start: int) -> tuple[OpLine, int]:
        """✏️ 訂單修改行 + 后续无 → 前缀的字段行组成一个 modify 事件。

        返回 (OpLine, 消费的后续行数)，外层游标据此跳过字段行。
        """
        fields = parse_modify_fields(line)
        consumed = 0
        i = start
        while i < len(lines):
            nxt = lines[i]
            nxt_stripped = nxt.strip()
            if not nxt_stripped or _ARROW_RE.match(nxt):
                break  # 空行或新的操作行（带 →）终止修改块
            extra = parse_modify_fields(nxt_stripped)
            if not any(extra.values()):
                break  # 非字段行终止
            _merge_fields(fields, extra)
            consumed += 1
            i += 1
        return (OpLine(action_type="modify", line_text=raw_line,
                       ts_text=_extract_ts(raw_line), mod_fields=fields), consumed)
