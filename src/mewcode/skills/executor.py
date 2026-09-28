"""Skill 执行器：inline 注入 / fork 起子 Agent（docs/ch11 T19，F26–F29）。

两条分支都先 `render_body` 产出最终文本：

- **inline**：把文本作为 user 消息注入主对话并触发一轮（`ui.inject_and_send`）
- **fork**：在 Python 端起一个受限子 Agent 跑完，把末尾 assistant 文本作为一条
  assistant 消息回流主对话（`ui.append_assistant_message`），用户看不出是 fork

fork 的隔离要点（都是踩过的坑）：
- 子 Agent 必须用**自己的 SessionRuntime**，否则两边互相覆盖 `usage_anchor`
- `Conversation.from_messages` 是**浅拷贝**，Message 对象与主对话共享，必须 deepcopy
- `Event.usage` 是**本轮**而非累计，要自行累加；回流用 `+=` 写主锚点，
  `anchor_msg_len` 不动（主对话历史长度没变，尾部估算仍按主 conv 算）
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import sys
from typing import TYPE_CHECKING, Any

from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.conversation import Conversation
from mewcode.llm import ROLE_ASSISTANT, Message, Provider, new_provider
from mewcode.permission import Engine, Mode
from mewcode.tool import Registry
from mewcode.tool.deferred import Discovery
from mewcode.tool.tool_search import ToolSearchTool

from .catalog import Catalog
from .parser import read_skill_body
from .render import render_body
from .types import Skill

if TYPE_CHECKING:
    from mewcode.agent import Agent, SessionRuntime
    from mewcode.command.ui import UI
    from mewcode.config import ProviderConfig

FORK_RECENT_N = 5  # fork_context=recent 取主对话末尾多少条（F28）
FORK_SUMMARY_HEADER = "[以下是本次会话已有上下文的摘要]"


def _warn(msg: str) -> None:
    print(f"[skills] warn: {msg}", file=sys.stderr)


def _spent(u: Any) -> int:
    """agent.Usage（input/output/cache_write/cache_read）→ 该轮总 token。

    注意字段名与 llm.Usage（input_tokens/output_tokens）不同——Event.usage 带的是
    前者，锚点计算原本用的是后者，这里是 fork 侧自行累加。
    """
    return u.input + u.output + u.cache_write + u.cache_read


def _last_assistant_text(conv: Conversation) -> str:
    """取末尾一条非空 assistant 文本作为 fork 结果（G5）。"""
    for msg in reversed(conv.messages()):
        if msg.role == ROLE_ASSISTANT and msg.content.strip():
            return msg.content
    return ""


class Executor:
    """Skill 的执行入口，由 Slash 命令 handler 调用。

    provider 与主 Agent **不在构造期注入**：多 provider 配置下要等用户在启动列表
    里选完才有 provider，而本对象在 cli 装配阶段就已构造。App 在 `_ensure_agent`
    里调 `bind()` 补上——inline 分支完全不依赖它们，fork 分支才需要。
    """

    def __init__(
        self,
        catalog: Catalog,
        registry: Registry,
        engine: Engine,
        version: str,
        runtime: "SessionRuntime",
        *,
        provider: Provider | None = None,
        main_agent: "Agent | None" = None,
        instruction_text: str = "",
        memory_text: str = "",
        provider_config: "ProviderConfig | None" = None,
    ) -> None:
        self._catalog = catalog
        self._registry = registry
        self._engine = engine
        self._version = version
        self._runtime = runtime
        self._provider = provider
        # 下面几项只有 fork 分支用得上：摘要需要主 Agent（它持有 runtime 全套状态），
        # 子 Agent 沿用主对话的指令/记忆文本与 provider 配置。
        self._main_agent = main_agent
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._provider_config = provider_config

    def bind(self, provider: Provider, agent: "Agent | None" = None) -> None:
        """provider 选定后由 App 调用，补齐 fork 分支所需依赖。"""
        self._provider = provider
        if agent is not None:
            self._main_agent = agent

    @property
    def active_skills(self) -> Any:
        return self._runtime.active_skills

    async def execute(self, name: str, args: str, ui: "UI") -> None:
        """跑一个 Skill；找不到只报错不抛异常（F26）。"""
        skill = self._catalog.get(name)
        if skill is None:
            ui.error(f"skill not found: {name}")
            return

        # 执行时重读磁盘，用户改了 SKILL.md 下次执行即生效（N5）
        fresh = dataclasses.replace(skill, prompt_body=read_skill_body(skill))
        rendered = render_body(fresh, args)

        if not skill.meta.is_fork():
            ui.inject_and_send(f"/{name}", rendered)
            return

        final_text = await self._run_fork(skill, rendered, ui)
        ui.append_assistant_message(final_text)

    async def _run_fork(self, skill: Skill, rendered: str, ui: "UI") -> str:
        """fork 分支：任何失败都退化成一条说明性 assistant 消息，不让主对话卡住（N7）。

        取消（`asyncio.CancelledError`）**不吞**：它与本仓库 agent 主循环的处理一致
        （`_stream_once` 也是直接 raise），且 TUI 的取消路径已负责收尾——吞掉会破坏
        任务可取消性。
        """
        try:
            return await self._fork_once(skill, rendered, ui)
        except Exception as exc:  # noqa: BLE001 —— 子 Agent 任何异常都降级为文本
            _warn(f"skill {skill.meta.name} fork failed: {exc}")
            return f"[skill {skill.meta.name} failed: {exc}]"

    async def _fork_once(self, skill: Skill, rendered: str, ui: "UI") -> str:
        # 延迟导入：skills 包在 session 态上被 agent 包依赖，运行时反向 import 会成环
        from mewcode.agent import Agent, SessionRuntime

        if self._provider is None:
            raise RuntimeError("no provider selected yet")

        sub_runtime = SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(ui.cwd() or "."),
            context_window=self._runtime.context_window,
        )
        registry, discovery = self._build_sub_registry(skill)
        conv = await self._build_fork_conv(skill, rendered, ui)

        agent = Agent(
            self._provider_for(skill),
            registry,
            self._version,
            self._engine,
            runtime=sub_runtime,
            instruction_text=self._instruction_text,
            memory_text=self._memory_text,
            discovery=discovery,
        )

        cancel = asyncio.Event()
        spent = 0
        async for ev in agent.run(conv, Mode.DEFAULT, cancel):
            if ev.usage is not None:
                spent += _spent(ev.usage)
            if ev.err is not None:
                raise ev.err

        # N6：fork 烧掉的 token 计入主锚点，后续压缩仍能感知；主对话长度没变，
        # anchor_msg_len 保持不动。
        self._runtime.usage_anchor += spent
        return _last_assistant_text(conv)

    def _build_sub_registry(self, skill: Skill) -> tuple[Registry, Discovery]:
        """按 allowed_tools 收窄工具集（F28/F30），系统工具豁免。

        做法是新建一个 Registry 只装白名单里的工具实例（Tool 可共享），而不是给
        Registry 加白名单视图——复用现有 Discovery 机制，隔离更彻底。
        """
        registry = Registry()
        for d in self._registry.definitions_filtered(skill.meta.allowed_tools):
            tool = self._registry.get(d.name)
            if tool is not None:
                registry.register(tool)

        discovery = Discovery(registry)
        if discovery.has_deferrable():
            # 与 cli 的主对话装配一致：有可延迟工具就要有 tool_search，否则
            # MCP 类工具在子 Agent 里永远不可见（deferrable 且未发现 = 不注入）
            registry.register(ToolSearchTool(discovery))
        return registry, discovery

    def _provider_for(self, skill: Skill) -> Provider:
        """按 Skill 的 `model` 覆盖 provider；`inherit`/空/不可用都退回主 provider。

        本期不做 `haiku` / `sonnet` / `opus` 这类别名解析——F8 只要求「可选字符串
        覆盖模型」，写成完整模型 id 即生效。
        """
        model = (skill.meta.model or "").strip()
        if not model or model == "inherit" or self._provider_config is None:
            return self._provider
        try:
            return new_provider(dataclasses.replace(self._provider_config, model=model))
        except Exception as exc:  # noqa: BLE001 —— 覆盖失败不该让 Skill 跑不起来
            _warn(f"skill {skill.meta.name}: model {model!r} unusable ({exc}), using current")
            return self._provider

    async def _build_fork_conv(self, skill: Skill, rendered: str, ui: "UI") -> Conversation:
        """按 `fork_context` 装填子 Agent 的初始对话（F28）。"""
        mode = skill.meta.fork_context

        if mode == "none":
            conv = Conversation()
        elif mode == "recent":
            conv = Conversation.from_messages(self._copy_recent(ui))
        else:  # full
            conv = Conversation()
            msgs = copy.deepcopy(ui.all_messages())
            summary = ""
            if msgs and self._main_agent is not None:
                try:
                    summary = await self._main_agent.summarize_for_fork(msgs)
                except Exception as exc:  # noqa: BLE001 —— 摘要失败退化成 recent
                    _warn(
                        f"skill {skill.meta.name}: fork summary failed ({exc}), "
                        "falling back to recent messages"
                    )
                    conv = Conversation.from_messages(self._copy_recent(ui))
            if summary:
                conv.add_user(f"{FORK_SUMMARY_HEADER}\n\n{summary}")

        conv.add_user(rendered)
        return conv

    def _copy_recent(self, ui: "UI") -> list[Message]:
        """主对话末尾 N 条消息的深拷贝。

        必须 deepcopy：`Conversation.from_messages` 只做列表级浅拷贝，Message 对象
        与主对话共享；压缩层的 ContentReplacementState 若原地改 content 会污染主对话。
        """
        return copy.deepcopy(ui.recent_messages(FORK_RECENT_N))
