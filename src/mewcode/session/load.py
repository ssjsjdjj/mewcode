"""会话加载恢复（docs/ch09 F14）。"""

from __future__ import annotations

import json
from pathlib import Path

from mewcode.llm import Message, ToolCall, ToolResult


def _truncate_orphaned_tool_calls(msgs: list[Message]) -> list[Message]:
    """若最后一条是带 tool_calls 的 assistant 且无后续 tool 结果 → 截断该条。

    孤立工具调用（压缩中断/进程被杀）缺结果消息，直接传给 provider 会报错，
    恢复时丢弃。独立成函数便于测试（docs/ch09 T6）。
    """
    if not msgs:
        return msgs
    last = msgs[-1]
    if last.role == "assistant" and last.tool_calls:
        return msgs[:-1]
    return msgs


def _entry_to_message(obj: dict) -> Message:
    """JSONL 行 dict → llm.Message；tool_calls/tool_results 结构同 llm 类型 asdict。"""
    return Message(
        role=obj.get("role") or "user",
        content=obj.get("content") or "",
        tool_calls=[ToolCall(**tc) for tc in obj.get("tool_calls") or []],
        tool_results=[ToolResult(**tr) for tr in obj.get("tool_results") or []],
    )


def load_session(session_dir: str) -> list[Message]:
    """从 conversation.jsonl 恢复消息列表。

    从最后一个 compact 标记之后加载（压缩前的旧消息已被摘要替代）；
    坏行跳过；结尾孤立工具调用截断。
    """
    jsonl = Path(session_dir) / "conversation.jsonl"
    if not jsonl.is_file():
        return []
    lines: list[dict] = []
    with open(jsonl, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # 坏行容错（docs/ch09 F14）
            lines.append(obj)
    # 从最后一个 compact 标记之后开始构建
    last_compact_index = -1
    for i, obj in enumerate(lines):
        if obj.get("type") == "compact":
            last_compact_index = i
    msgs = [_entry_to_message(obj) for obj in lines[last_compact_index + 1 :]]
    return _truncate_orphaned_tool_calls(msgs)
