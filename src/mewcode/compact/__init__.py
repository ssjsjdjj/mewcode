"""上下文管理子包（ch08 两层防御）。

外层唯一入口 manage_context；TriggerKind 标明触发来源；State 类型承载跨轮状态。
"""

from __future__ import annotations

from .compact import ManageInput, ManageOutput, TriggerKind, manage_context
from .state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    FileReadRecord,
    RecoveryState,
    SessionContext,
    new_session_context,
    open_session_context,
    parse_session_time,
)

__all__ = [
    "CompactCircuitBreaker",
    "ContentReplacementState",
    "FileReadRecord",
    "ManageInput",
    "ManageOutput",
    "RecoveryState",
    "SessionContext",
    "TriggerKind",
    "manage_context",
    "new_session_context",
    "open_session_context",
    "parse_session_time",
]
