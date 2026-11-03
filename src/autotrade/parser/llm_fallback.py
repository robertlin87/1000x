"""LLM 兜底解析（可选）：模板未命中时用 OpenAI JSON 输出同 Signal 结构。"""
from __future__ import annotations


async def llm_parse(text: str, api_key: str | None = None):
    """TODO 可选（M1 后期）：格式漂移时的兜底解析，输出结构同 entry_parser.Signal。"""
    raise NotImplementedError("可选")
