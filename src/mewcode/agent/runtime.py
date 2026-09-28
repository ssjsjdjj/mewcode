"""会话运行时状态（docs/ch08 T26）。

每会话一份，承载上下文管理的跨轮状态；Agent 主循环每轮请求前据此组装
ManageInput。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from mewcode.skills import ActiveSkills


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

    def reset_for_new_session(self, ses_ctx: SessionContext) -> None:
        """原子重置跨轮状态并切换到新会话（docs/ch10 T0c，/clear 场景）。

        三个 compact 子状态换新、用量锚点与回合计数清零、session 指向新上下文；
        context_window 保留（由启动期配置决定，与具体会话无关）。writer 与
        conversation 的重建由调用方负责，不进本接口。

        ch11 起同时清空已激活 Skill——它是会话态（docs/ch11 T25）。`/clear`
        的 handler 还会在新建 writer **之前**再清一次以满足 N9 的顺序要求，
        两处都不算多余：这里保证「会话重置 ⇒ 激活态重置」，那里保证时序。
        """
        self.replacement = ContentReplacementState()
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = ses_ctx
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.turn_count = 0
        self.active_skills.clear()
