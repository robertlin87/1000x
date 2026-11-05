"""LLM 兜底解析（可選）：模板未命中時用 OpenAI JSON 輸出同 Signal 結構。"""
from __future__ import annotations


async def llm_parse(text: str, api_key: str | None = None):
    """TODO 可選（M1 後期）：格式漂移時的兜底解析，輸出結構同 entry_parser.Signal。"""
    raise NotImplementedError("可選")
