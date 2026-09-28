"""上下文压缩对外状态事件（docs/ch08 T29a，兑现 spec F24a/F24b）。

TUI 据此展示「已压缩，token 从 X 降至 Y」；事件只表达状态，不改对话历史。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CompactPhase(Enum):
    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"


@dataclass
class CompactEvent:
    phase: CompactPhase
    before: int = 0
    after: int = 0
    err: Exception | None = None
