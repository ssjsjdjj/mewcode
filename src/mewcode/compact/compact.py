"""上下文管理编排入口（ch08 T18）。

manage_context 是 Agent 每轮请求前调用的唯一入口，编排第 1/2 层防御与
自动 / 手动 / 紧急三路，并把替换 / 摘要结果写回 Conversation。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from mewcode.conversation import Conversation
from mewcode.llm import Provider, ToolDefinition

from .const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from .layer1 import offload_and_snip
from .layer2 import auto_compact, force_compact
from .state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from .token import estimate_tokens

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    """manage_context 完整入参（Agent 每轮请求前组装一次）。"""

    conv: Conversation
    provider: Provider
    model: str
    context_window: int
    tool_defs: list[ToolDefinition]  # 当前轮按 mode 选用的工具定义列表
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int  # 上一次主对话 stream 的真实 usage 之和
    anchor_msg_len: int  # anchor 时的 conv.length()
    estimated_token: int  # 调用方估算的当前总 token（= anchor + chars/3.5）
    trigger: TriggerKind


@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int


async def manage_context(in_: ManageInput) -> ManageOutput:
    """Agent 每轮请求前调用的唯一入口。

    MANUAL：跳过 layer1、阈值、熔断，直接 force_compact。
    EMERGENCY：先强制跑一次 layer1 挪走大工具结果，再 force_compact。
    AUTO：先跑 layer1 并写回，用 layer1_out 重估 token 判断是否触发 layer2；
          熔断 / 低于阈值 / 窗口过小时仅 layer1 生效。
    """
    if in_.trigger is TriggerKind.MANUAL:
        new_msgs, before_tok, after_tok = await force_compact(in_)
        in_.conv.replace_history(new_msgs)
        return ManageOutput(before_tokens=before_tok, after_tokens=after_tok)

    if in_.trigger is TriggerKind.EMERGENCY:
        layer1_out = offload_and_snip(in_.conv.messages(), in_.replacement, in_.session)
        in_.conv.replace_history(layer1_out)
        new_msgs, before_tok, after_tok = await force_compact(in_)
        in_.conv.replace_history(new_msgs)
        return ManageOutput(before_tokens=before_tok, after_tokens=after_tok)

    # AUTO 路径
    layer1_out = offload_and_snip(in_.conv.messages(), in_.replacement, in_.session)
    in_.conv.replace_history(layer1_out)  # 无论是否触发 layer2 都必须写回
    est_tokens = estimate_tokens(in_.usage_anchor, layer1_out, in_.anchor_msg_len)

    if in_.context_window <= SUMMARY_RESERVE + AUTO_SAFETY_MARGIN:
        logger.warning(
            "context_window 过小（<= %d），跳过自动第 2 层", SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
        )
        return ManageOutput(before_tokens=in_.estimated_token, after_tokens=est_tokens)

    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    if est_tokens < threshold or in_.auto_tracking.tripped():
        return ManageOutput(before_tokens=in_.estimated_token, after_tokens=est_tokens)

    new_msgs, before_tok, after_tok = await auto_compact(in_)
    in_.conv.replace_history(new_msgs)
    return ManageOutput(before_tokens=before_tok, after_tokens=after_tok)
