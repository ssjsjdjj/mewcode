"""Agent 包（docs/ch04；ch08 T26 起拆分为 runtime.py / agent.py）。

对外 API 与原单模块一致：Agent / Event / Phase 等现有调用方无需改动 import。
"""

from .agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_STREAM_ERR,
    NOTICE_UNKNOWN_TOOLS,
    PLAN_REMINDER_INTERVAL,
    Agent,
    ApprovalRequest,
    Event,
    Phase,
    ToolEvent,
    Usage,
)
from .event import CompactEvent, CompactPhase
from .runtime import SessionRuntime

__all__ = [
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "PLAN_REMINDER_INTERVAL",
    "Agent",
    "ApprovalRequest",
    "CompactEvent",
    "CompactPhase",
    "Event",
    "Phase",
    "SessionRuntime",
    "ToolEvent",
    "Usage",
]
