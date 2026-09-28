"""会话运行时状态（docs/ch08 T26）。

每会话一份，承载上下文管理的跨轮状态；Agent 主循环每轮请求前据此组装
ManageInput。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from mewcode.skills import ActiveSkills

if TYPE_CHECKING:
    from mewcode.hook import Engine


@dataclass
class SessionRuntime:
    """每会话跨轮的上下文管理运行时状态。

    usage_anchor 只在主对话路径 stream 成功后更新（摘要请求不更新）。
    """

    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    usage_anchor: int = 0  # 主对话路径 stream 真实 usage 之和；摘要请求不更新
    anchor_msg_len: int = 0  # anchor 当时 conv.length()
    turn_count: int = 0  # 自然完成轮数累计（docs/ch09 F25 记忆触发节奏）
    # 已激活 Skill 的 SOP 列表（docs/ch11 T25）。与会话同生命周期；
    # 新字段必须带默认值且追加在末尾——cli 与测试都按位置构造本 dataclass。
    active_skills: ActiveSkills = field(default_factory=ActiveSkills)
    # hook 注入的待发 reminder（docs/ch12 T14）。仅本轮有效：装进请求后即取空，
    # 不入持久历史、不参与压缩（F21/N4）。
    pending_reminders: list[str] = field(default_factory=list)
    hook_engine: Engine | None = None  # cli 注入；None 时所有 hook 相关动作退化

    def reset_for_new_session(self, ses_ctx: SessionContext) -> None:
        """原子重置跨轮状态并切换到新会话（docs/ch10 T0c，/clear 场景）。

        三个 compact 子状态换新、用量锚点与回合计数清零、session 指向新上下文；
        context_window 保留（由启动期配置决定，与具体会话无关）。writer 与
        conversation 的重建由调用方负责，不进本接口。

        ch11 起同时清空已激活 Skill——它是会话态（docs/ch11 T25）。`/clear`
        的 handler 还会在新建 writer **之前**再清一次以满足 N9 的顺序要求，
        两处都不算多余：这里保证「会话重置 ⇒ 激活态重置」，那里保证时序。

        ch12 起也清空 pending_reminders；**hook 引擎的 only_once 集合不在这里清**
        ——那是个 async 操作，而本方法是同步的（被 `clear_and_new_session` 同步
        调用）。改公开 API 为 async 只为内部重置不划算，改由 TUI 在 `/clear` /
        `/resume` 时单独 `await engine.reset_for_new_session()`（docs/ch12 T20）。
        """
        self.replacement = ContentReplacementState()
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = ses_ctx
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.turn_count = 0
        self.active_skills.clear()
        self.pending_reminders = []

    def append_reminders(self, prompts: list[str]) -> None:
        """追加待注入文本（hook 的 prompt 动作）。

        不加锁：本方法体内没有 await，append 是原子操作，asyncio 单线程下不会
        与 `take_reminders` 交错。
        """
        self.pending_reminders.extend(prompts)

    def take_reminders(self) -> list[str]:
        """取出并清空待注入文本；每次请求前调用一次（F20/F33）。"""
        items = self.pending_reminders
        self.pending_reminders = []
        return items
