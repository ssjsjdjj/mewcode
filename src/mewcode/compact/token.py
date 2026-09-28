"""token 估算（ch08 T5）。

锚点语义：上一次主对话 stream 的真实 usage 之和为锚，只对锚点之后追加的
消息做字符增量估算，避免重复计算历史。所有长度按 UTF-8 字节。
"""

from __future__ import annotations

import json
import math

from mewcode.llm import Message, Usage

from .const import ESTIMATE_CHARS_PER_TOKEN


def usage_anchor(u: Usage) -> int:
    """一次 stream 的真实 token 锚点：输入 + 输出 + 缓存读 + 缓存写。"""
    return u.input_tokens + u.output_tokens + u.cache_read + u.cache_write


def message_chars(msgs: list[Message]) -> int:
    """估算消息列表的 UTF-8 字节总长（含工具调用参数与工具结果）。"""
    total = 0
    for msg in msgs:
        if msg.content:
            total += len(msg.content.encode("utf-8"))
        for call in msg.tool_calls:
            if isinstance(call.input, str):
                total += len(call.input.encode("utf-8"))
            else:
                total += len(json.dumps(call.input).encode("utf-8"))
        for result in msg.tool_results:
            if result.content:
                total += len(result.content.encode("utf-8"))
    return total


def estimate_tokens(anchor: int, all_msgs: list[Message], anchor_msg_len: int) -> int:
    """估算当前对话总 token：锚点真实用量 + 锚点之后增量的字符估算。"""
    tail = all_msgs[max(0, anchor_msg_len) :]
    return anchor + math.ceil(message_chars(tail) / ESTIMATE_CHARS_PER_TOKEN)
