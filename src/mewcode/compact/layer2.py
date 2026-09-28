"""第 2 层防御：LLM 摘要压缩（ch08 T12~T17）。

run_summary 产出"摘要 + 恢复附件 + 近期原文"三段，拼成新的 conversation。
摘要请求自带 PTL 重试（ptl_retry），失败路径计入/不计入熔断器由 auto/force 决定。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from mewcode.llm import Message, PromptTooLongError, Request, ROLE_ASSISTANT, ROLE_USER

from .const import (
    ESTIMATE_CHARS_PER_TOKEN,
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
)
from .recovery import build_recovery_attachment
from .summary_prompt import build_summary_prompt, extract_summary
from .token import estimate_tokens, message_chars

if TYPE_CHECKING:
    from .compact import ManageInput


def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从尾到头挑近期原文：累计 token ≥ RECENT_KEEP_TOKENS 且条数 ≥
    RECENT_KEEP_MESSAGES（两个下界都满足才停手，覆盖范围更大）；再配对修正，
    起点若落在 tool_result 上则前推到上一组带 tool_calls 的 assistant。"""
    if not msgs:
        return []
    start_idx = 0
    total_tokens = 0
    count = 0
    for i in range(len(msgs) - 1, -1, -1):
        total_tokens += math.ceil(message_chars([msgs[i]]) / ESTIMATE_CHARS_PER_TOKEN)
        count += 1
        if total_tokens >= RECENT_KEEP_TOKENS and count >= RECENT_KEEP_MESSAGES:
            start_idx = i
            break
    if start_idx < len(msgs) and msgs[start_idx].role == "tool":
        j = start_idx - 1
        while j >= 0:
            if msgs[j].role == "assistant" and msgs[j].tool_calls:
                start_idx = j
                break
            j -= 1
    return list(msgs[start_idx:])


def _join_after_summary(summary_and_recovery: Message, recent: list[Message]) -> list[Message]:
    """把摘要+恢复消息接到近期原文前面；防御性丢掉落单 tool_result，
    并对 user 开头插入 assistant 占位，避免 user/user 连续违反 anthropic 协议。"""
    if not recent:
        return [summary_and_recovery]
    idx = 0
    while idx < len(recent) and recent[idx].role == "tool":
        idx += 1  # 防御性：pick_recent_tail 配对修正未兜住时丢掉落单 tool_result
    recent = recent[idx:]
    if not recent:
        return [summary_and_recovery]
    if recent[0].role == ROLE_USER:
        bridge = Message(role=ROLE_ASSISTANT, content="（已加载上下文摘要与恢复信息。请继续。）")
        return [summary_and_recovery, bridge, *recent]
    return [summary_and_recovery, *recent]


def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按 user 消息切组：每条 user 开新组，其后消息同组追加；
    首条非 user 时单独成第 0 组防止丢失。不修改入参。"""
    groups: list[list[Message]] = []
    for msg in msgs:
        if msg.role == ROLE_USER:
            groups.append([msg])
        elif groups:
            groups[-1].append(msg)
        else:
            groups.append([msg])
    return groups


async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    """单次摘要请求：返回 extract_summary 提取的摘要文本。

    异常透传：err 事件（含 PromptTooLongError）立即 raise，让上层 isinstance 命中；
    usage 事件捕获但不回写主对话锚点（摘要请求不算主对话）。
    """
    req = Request(messages=build_summary_prompt(msgs), tools=[])
    text_buf: list[str] = []
    async for ev in in_.provider.stream(req):
        if ev.err is not None:
            raise ev.err
        if ev.text:
            text_buf.append(ev.text)
        # ev.usage：摘要请求不更新 usage_anchor，忽略
    return extract_summary("".join(text_buf))


async def ptl_retry(in_: ManageInput, msgs: list[Message], first_err: Exception) -> str:
    """摘要请求的 PTL 自重试：前 PTL_RETRY_LIMIT 次逐组丢最旧 1 组，之后按
    比例丢；全部丢光仍失败时抛最近一次 err，绝不发送 messages 为空的请求。"""
    groups = group_by_user_turn(msgs)
    retries = 0
    last_err = first_err
    while groups:
        if retries < PTL_RETRY_LIMIT:
            groups = groups[1:]  # 丢最旧 1 组
        else:
            drop = math.ceil(len(groups) * PTL_DROP_PERCENTAGE)
            groups = groups[drop:]
        retries += 1
        if not groups:
            break
        flat = [m for g in groups for m in g]
        try:
            return await summarize_once(in_, flat)
        except PromptTooLongError as err:
            last_err = err
        # 非 PTL 异常：立即上抛，不再重试
    raise last_err


async def run_summary(in_: ManageInput) -> list[Message]:
    """第 2 层主流程：摘要（含 PTL 重试）+ 恢复附件 + 近期原文，三段拼接。"""
    old_msgs = in_.conv.messages()
    recovery_snapshot = in_.recovery.snapshot()  # 入口拍快照，渲染期间不漂移
    try:
        summary_text = await summarize_once(in_, old_msgs)
    except PromptTooLongError as err:
        summary_text = await ptl_retry(in_, old_msgs, err)

    recovery_text = build_recovery_attachment(recovery_snapshot, in_.tool_defs)
    combined_content = "## 历史会话摘要\n" + summary_text + "\n\n" + recovery_text
    summary_and_recovery = Message(role=ROLE_USER, content=combined_content)

    recent_tail = pick_recent_tail(old_msgs)
    return _join_after_summary(summary_and_recovery, recent_tail)


async def auto_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """自动压缩：失败记录熔断 + 上抛；成功记录 success 并估算压缩后 token。"""
    before_tok = in_.estimated_token
    try:
        new_msgs = await run_summary(in_)
    except Exception as err:
        in_.auto_tracking.record_failure()
        if not hasattr(err, "before_tokens"):
            err.before_tokens = before_tok  # type: ignore[attr-defined]
        raise
    in_.auto_tracking.record_success()
    after_tok = estimate_tokens(0, new_msgs, 0)
    return (new_msgs, before_tok, after_tok)


async def force_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """强制压缩（手动/紧急）：不触碰熔断器，失败直接上抛。"""
    before_tok = in_.estimated_token
    new_msgs = await run_summary(in_)
    after_tok = estimate_tokens(0, new_msgs, 0)
    return (new_msgs, before_tok, after_tok)
