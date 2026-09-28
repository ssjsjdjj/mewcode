"""第 1 层防御：工具结果落盘替换（ch08 T6~T8）。

确定性、非 LLM：把超大工具结果 spill 到会话目录，原地替换为固定格式预览体，
并把决策冻结在 ContentReplacementState 账本里，保证跨轮 prompt-cache 稳定。
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from mewcode.llm import Message, ROLE_TOOL

from .const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from .state import ContentReplacementState, SessionContext

logger = logging.getLogger(__name__)


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """把单条工具结果写到 `<spill_dir>/<tool_use_id>`；文件已存在则跳过（幂等）。

    写失败让 OSError 自然抛出，由调用方决定是否重试。
    """
    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        return
    path.write_bytes(content.encode("utf-8"))


def _head_preview(content: str) -> str:
    """取头部预览：先按行截到 PREVIEW_HEAD_LINES 行，再按字节二次截断。"""
    head = "".join(content.splitlines(keepends=True)[:PREVIEW_HEAD_LINES])
    if len(head.encode("utf-8")) > PREVIEW_HEAD_BYTES:
        # 字节级截断，errors="ignore" 丢弃落在边界上的半个多字节字符
        head = head.encode("utf-8")[:PREVIEW_HEAD_BYTES].decode("utf-8", errors="ignore")
    return head


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造固定格式的预览体，逐字节稳定。"""
    return "\n".join(
        [
            f"[content offloaded] original size: {original_bytes} bytes",
            f"[saved to] {spill_path}",
            "[head preview]",
            head,
            "完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文",
        ]
    )


def _spill_decision(session: SessionContext, tool_use_id: str, content: str) -> tuple[str, str]:
    """落盘决策回调：成功返回 replaced，失败返回 skip（不写账本，下轮重试）。"""
    try:
        spill_single(session, tool_use_id, content)
    except OSError:
        logger.warning("tool result 落盘失败，保留原文并下轮重试: %s", tool_use_id)
        return ("skip", "")
    spill_path = str(Path(session.spill_dir) / tool_use_id)
    return (
        "replaced",
        build_preview(len(content.encode("utf-8")), _head_preview(content), spill_path),
    )


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """第 1 层：把超大工具结果落盘并替换为预览体，返回深拷贝后的新列表。

    只处理 ROLE_TOOL 消息（工具结果挂在 tool 消息的 tool_results 里）。
    对已决策项复用账本冻结结果；未决策项按字节倒序处理：
      单条 > SINGLE_RESULT_LIMIT 必须落盘；否则在聚合字节超限时继续按倒序落盘，
      直至剩余聚合 ≤ MESSAGE_AGGREGATE_LIMIT。落盘失败经 "skip" 决策吞掉并下轮重试。
    """
    out = copy.deepcopy(msgs)
    for msg in out:
        if msg.role != ROLE_TOOL:
            continue
        results = msg.tool_results
        # 探测已决策项：("skip", "") 是纯探测，不写账本。
        # 已 Seen 的 replaced 项会返回冻结的预览体（!= 原 content），直接复用；
        # 已 Seen 的 kept 项与未决策项都返回原 content，作为候选进入下一阶段。
        candidates: list[tuple[int, str, str]] = []  # (index, tool_call_id, content)
        for j, res in enumerate(results):
            frozen = state.decide_once(res.tool_call_id, res.content or "", lambda: ("skip", ""))
            if frozen != (res.content or ""):
                results[j].content = frozen
            else:
                candidates.append((j, res.tool_call_id, res.content or ""))

        candidates.sort(key=lambda item: len(item[2].encode("utf-8")), reverse=True)
        # 当前剩余聚合字节：以 results 当前内容（含已复用预览体）为准
        total = sum(len(r.content.encode("utf-8")) for r in results)

        for j, tool_use_id, content in candidates:
            size = len(content.encode("utf-8"))
            if not (size > SINGLE_RESULT_LIMIT or total > MESSAGE_AGGREGATE_LIMIT):
                break
            new_content = state.decide_once(
                tool_use_id,
                content,
                lambda id_=tool_use_id, c=content: _spill_decision(session, id_, c),
            )
            if new_content != content:
                results[j].content = new_content
                total -= size
    return out
