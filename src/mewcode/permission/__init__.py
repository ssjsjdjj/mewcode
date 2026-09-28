"""权限系统（docs/ch06）：五层防御的判定类型与对外门面。

五层：黑名单 → 沙箱 → 规则引擎 → 模式兜底（前四层在 Engine.check 内短路）；
第五层人在回路由 agent 在 Ask 后编排驱动。
"""

from __future__ import annotations

from enum import IntEnum


class Mode(IntEnum):
    """四档权限模式（docs/ch06 F5）。"""

    DEFAULT = 0  # 只读 Allow / 文件写 Ask / 命令执行 Ask
    ACCEPT_EDITS = 1  # 文件写 Allow / 命令执行 Ask
    PLAN = 2  # 仅只读工具可见；矩阵同 default 作防御兜底
    BYPASS = 3  # 全 Allow（黑名单/沙箱仍拦）

    def __str__(self) -> str:
        return _MODE_NAMES[self]


_MODE_NAMES = {
    Mode.DEFAULT: "default",
    Mode.ACCEPT_EDITS: "acceptEdits",
    Mode.PLAN: "plan",
    Mode.BYPASS: "bypassPermissions",
}
_MODE_LOOKUP = {name.lower(): mode for mode, name in _MODE_NAMES.items()}


def parse_mode(s: str) -> tuple[Mode, bool]:
    """大小写不敏感识别四档名；未知返回 (Mode.DEFAULT, False)。"""
    mode = _MODE_LOOKUP.get(s.lower())
    if mode is None:
        return Mode.DEFAULT, False
    return mode, True


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    """人在回路三选一（docs/ch06 F8）。"""

    DENY_ONCE = 0  # 拒绝本次
    ALLOW_ONCE = 1  # 允许本次（不留规则）
    ALLOW_FOREVER = 2  # 永久允许（写本地层文件，精确匹配）


class ApprovalError(Exception):
    """权限相关错误（agent 侧捕获、不阻断执行）。"""


# 引擎符号在类型定义之后导入，避免循环导入
from .engine import Engine, check, new_engine, persist_local_allow, start_mode  # noqa: E402,F401
