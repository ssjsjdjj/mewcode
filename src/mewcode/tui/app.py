"""MewCodeApp：状态机 + 布局 + 提交/选择/退出（docs/ch02 T9/T11）。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label, OptionList, RichLog, Static, TextArea

from mewcode import __version__
from mewcode.agent import Agent, SessionRuntime
from mewcode.command.builtins import register_builtins
from mewcode.command.registry import Registry
from mewcode.config import ProviderConfig, effective_context_window
from mewcode.hook import DispatchResult
from mewcode.hook import Event as HookEvent
from mewcode.llm import Provider, ToolDefinition, new_provider
from mewcode.permission import Engine, Mode, Outcome, new_engine
from mewcode.prompt import render_banner
from mewcode.session import SessionInfo
from mewcode.tool.deferred import Discovery
from mewcode.tui import ChatInput, SessionState, ToolDisplay
from mewcode.tui.commands import CommandMixin, CompactDone, format_compact_notice
from mewcode.tui.complete import (
    CompletionMenu,
    _execute_selected,
    _handle_completion_key,
    _sync_completion_from_input,
)
from mewcode.tui.resume import do_resume_session, handle_resume_key
from mewcode.tui.stream import StreamingMixin
from mewcode.tui.view import approval_block, notice_block, status_text


_OUTCOME_BY_INDEX = [
    Outcome.ALLOW_ONCE,  # 1. 允许本次
    Outcome.ALLOW_FOREVER,  # 2. 永久允许
    Outcome.DENY_ONCE,  # 3. 拒绝本次
]


class MewCodeApp(StreamingMixin, CommandMixin, App):
    """终端对话主应用。"""

    TITLE = "mewcode"
    # 补全相关 App 方法定义在 complete.py，此处绑定（docs/ch10 T11）
    _handle_completion_key = _handle_completion_key
    _execute_selected = _execute_selected
    _sync_completion_from_input = _sync_completion_from_input
    CSS = """
    Screen { layout: vertical; }
    #log { height: 1fr; border: round $surface; padding: 0 1; margin: 0 1; }
    #streaming { height: auto; padding: 0 1; color: $text-muted; }
    #select { height: auto; margin: 0 1; }
    #input-row { height: auto; margin: 0 1; }
    #input-row > Label { padding: 1 0 0 1; color: $accent; }
    #chat-input { height: auto; min-height: 1; max-height: 8; }
    #completion { height: auto; max-height: 12; padding: 0 1; color: $text-muted; }
    #statusbar { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit/Cancel"),
        Binding("escape", "cancel_turn", "Cancel"),
    ]

    state = reactive(SessionState.IDLE)

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str = __version__,
        registry: Any = None,
        provider: Provider | None = None,
        engine: Engine | None = None,
        runtime: SessionRuntime | None = None,
        *,
        writer: Any = None,
        mem_mgr: Any = None,
        instruction_text: str = "",
        memory_text: str = "",
        discovery: Any = None,
        catalog: Any = None,
        executor: Any = None,
        hook_engine: Any = None,
    ) -> None:
        super().__init__()
        self._providers = providers
        self._version = version
        # ch11 Skill：Catalog 供 /skill 与 LoadSkill 清单；Executor 供 /<name> 命令。
        # 两者由 cli 装配后注入；直接构造 App 的测试场景留空即退化为「无 Skill」。
        self.catalog = catalog
        self.executor = executor
        # ch12 Hook：None 时所有 emit 退化成空操作（与 ch11 行为一致）
        self.hook_engine = hook_engine
        self.tool_registry = (
            registry  # ch03：tool registry（勿用 _registry，与 textual 内部属性冲突）
        )
        # 延迟加载视图（docs/ch07 追加 T15）：cli 注入；直接构造 App 的场景（测试）
        # 未注入时按 registry 自建一份——自建者恒无已发现工具，等价旧行为。
        self.discovery = discovery
        if self.discovery is None and registry is not None:
            self.discovery = Discovery(registry)
        # ch10 slash 命令系统（docs/ch10 T8.5/T9c）：builtins 一次注册、跨 App 复用
        self.cmd_registry = Registry()
        register_builtins(self.cmd_registry)
        self.completion = CompletionMenu()  # / 补全菜单状态（T11 渲染）
        self._pending_println: list[str] = []  # dispatch_slash 内收集的待渲染输出
        self._cwd = os.getcwd()  # 工作区（/status、/clear 的会话目录数据源）
        self.engine = engine or new_engine(".")[0]
        self.runtime = runtime  # cli 注入的会话级 runtime（docs/ch08 T32.5）
        self.agent: Agent | None = None  # 会话级 Agent，跨轮复用
        self.provider = provider
        # ch09 会话持久化（docs/ch09 T14/T16）：_bind_conversation 把 writer 的
        # 追加/替换回调挂到 Conversation 上，每条消息实时落盘 JSONL
        self.writer = writer  # 当前会话存档 Writer
        self.mem_mgr = mem_mgr  # 记忆管理器（延迟到 provider 选定后 set_provider）
        self.instruction_text = instruction_text  # 三层 MEWCODE.md 指令文本
        self.memory_text = memory_text  # 记忆索引文本
        self.ses_ctx = runtime.session if runtime is not None else None  # 当前会话上下文
        self.sessions_dir = (
            str(Path(self.ses_ctx.session_dir).parent) if self.ses_ctx is not None else ""
        )
        self.resume_items: list[SessionInfo] = []  # RESUMING 态会话列表
        self.conv = self._bind_conversation(writer)
        self.cur_reply = ""
        self._mode = self.engine.start_mode  # 权限模式存储，跨轮保持（docs/ch06 F7）
        self.iter = 0  # 当前迭代轮次（进度显示）
        self._usage_in = 0  # 会话累计输入 token
        self._usage_out = 0  # 会话累计输出 token
        self.cur_tools: list[ToolDisplay] = []  # 执行中工具（支持并发批多个）
        self.pending = None  # 待批准请求（APPROVING 态）
        self.approve_cursor = 0  # 待批准菜单光标
        self.turn_cancel: asyncio.Event | None = None  # 本轮取消事件
        self.turn_start = 0.0
        self._stream_task: asyncio.Task | None = None
        self._timer = None

    # ---- 布局 ----

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=True)
        yield Static(id="streaming")
        yield OptionList(id="select")
        with Horizontal(id="input-row"):
            yield Label("❯")
            yield ChatInput(id="chat-input", placeholder="Send a message...")
        yield Static("", id="completion")  # / 命令补全菜单（docs/ch10 T13）
        yield Static(id="statusbar")

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).write(render_banner(self._version, os.getcwd()))
        if len(self._providers) == 1:
            if self.provider is None:
                self.provider = new_provider(self._providers[0])
            self._ensure_agent()
            self.state = SessionState.IDLE
            self._update_statusbar()
        else:
            self._populate_select()
            self.state = SessionState.SELECTING
        # SessionStart 在挂载后立刻分派（docs/ch12 T18/T20）：此时 env context 已可
        # 装配、首条 user 消息还没进历史，正是 F9 定义的时刻。与 _begin_turn 一样用
        # create_task，不阻塞挂载。
        asyncio.create_task(self._dispatch_session_start())

    # ---- Hook 会话事件（docs/ch12 T18/T20）----

    def _hook_payload(self, event: HookEvent, **extra: Any) -> dict:
        """hook payload 的通用字段 + 事件特化字段（F10）。

        TUI 侧各事件（SessionStart/End/Resume、UserPromptSubmit）共用本方法，
        agent 侧另有自己的同名方法（它拿不到 App 的 cwd 与模式）。
        """
        payload: dict = {
            "event": event.value,
            "session_id": self.session_id(),
            "cwd": self._cwd,
            "mode": str(self._mode),
        }
        payload.update(extra)
        return payload

    async def _dispatch_hook(self, event: HookEvent, **extra: Any) -> DispatchResult | None:
        """分派一次事件并把注入的 prompt 排进 runtime 队列；无引擎时返回 None。"""
        if self.hook_engine is None:
            return None
        result = await self.hook_engine.dispatch(event, self._hook_payload(event, **extra))
        if result.injected_prompts and self.runtime is not None:
            self.runtime.append_reminders(result.injected_prompts)
        return result

    async def _dispatch_session_start(self) -> None:
        await self._dispatch_hook(HookEvent.SESSION_START)

    async def _dispatch_session_end(self) -> None:
        await self._dispatch_hook(HookEvent.SESSION_END)

    async def _dispatch_session_resume(self) -> None:
        await self._dispatch_hook(HookEvent.SESSION_RESUME)

    def watch_state(self, old: SessionState, new: SessionState) -> None:
        if not self.is_mounted:
            return
        select = self.query_one("#select", OptionList)
        input_row = self.query_one("#input-row")
        chat_input = self.query_one("#chat-input", ChatInput)
        # RESUMING 与 SELECTING 共用 #select 列表（docs/ch09 T14）
        select.display = new in (SessionState.SELECTING, SessionState.RESUMING)
        input_row.display = new not in (SessionState.SELECTING, SessionState.RESUMING)
        chat_input.disabled = new in (SessionState.STREAMING, SessionState.APPROVING)
        if new in (SessionState.SELECTING, SessionState.RESUMING):
            select.focus()
        elif new == SessionState.IDLE:
            chat_input.focus()

    # ---- provider 选择 ----

    def _populate_select(self) -> None:
        select = self.query_one("#select", OptionList)
        select.clear_options()
        for p in self._providers:
            select.add_option(f"{p.name} ({p.model})")
        select.action_first()  # 高亮第一项，否则 enter 选中会因 highlighted=None 失效

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.state == SessionState.RESUMING:
            # 鼠标点击会话项：与键盘 Enter 走同一恢复流程（键盘已在 handle_resume_key 拦截）
            idx = event.option_index
            if 0 <= idx < len(self.resume_items):
                asyncio.create_task(do_resume_session(self, self.resume_items[idx]))
            self.state = SessionState.IDLE
            return
        cfg = self._providers[event.option_index]
        self.provider = new_provider(cfg)
        # 多 provider：选中后才知 protocol，回填 context_window（docs/ch08 T32）
        if self.runtime is not None:
            self.runtime.context_window = effective_context_window(cfg)
        self._ensure_agent()
        self._update_statusbar()
        self.state = SessionState.IDLE

    def _ensure_agent(self) -> None:
        """会话级 Agent 只构造一次，跨轮复用（docs/ch08 T32.5）。

        provider 选定的统一落点（on_mount 单 provider / 选择列表多 provider）：
        在此回填记忆 provider，并把指令/记忆文本与记忆管理器注入 Agent（ch09 T16）。
        """
        if self.agent is None and self.provider is not None:
            if self.mem_mgr is not None:
                self.mem_mgr.set_provider(self.provider, self.provider.model)
            self.agent = Agent(
                self.provider,
                self.tool_registry,
                self._version,
                self.engine,
                runtime=self.runtime,
                instruction_text=self.instruction_text,
                memory_text=self.memory_text,
                memory_manager=self.mem_mgr,
                discovery=self.discovery,
                hook_engine=self.hook_engine,
            )
            # Skill 清单进稳定系统提示（docs/ch11 F21）；loader 工具要能激活
            self.agent.with_catalog(self.catalog)
            # fork 分支要 provider 与主 Agent（摘要用），此处才算齐备（ch11 T27）
            if self.executor is not None:
                self.executor.bind(self.provider, self.agent)

    def visible_tool_defs(self) -> list[ToolDefinition]:
        """本轮可见的工具定义（docs/ch07 追加 T15）。

        与 Agent 主循环同一口径（`visible_definitions(mode == Mode.PLAN)`）：手动
        `/compact` 与 `/resume` 的压缩要把 tool_defs 交给压缩层估算，口径不一致会
        让两次压缩的 token 估算对不上。

        这是全局唯一的 `defs` 出处（AC23）；没有 discovery 就没有延迟语义，退回全集。
        """
        if self.discovery is not None:
            return self.discovery.visible_definitions(plan_only=self._mode == Mode.PLAN)
        if self.tool_registry is None:  # 未注入注册中心（仅直接构造 App 的场景）
            return []
        return self.tool_registry.definitions()

    def _update_statusbar(self) -> None:
        if self.provider is not None:
            self.query_one("#statusbar", Static).update(
                status_text(
                    self.provider.model,
                    mode=self._mode,
                    usage_in=self._usage_in,
                    usage_out=self._usage_out,
                )
            )

    def on_compact_done(self, message: CompactDone) -> None:
        """手动 /compact 回投：复用统一压缩文案（docs/ch08 T33/T34a）。"""
        self.query_one("#log", RichLog).write(notice_block(format_compact_notice(message.event)))

    # ---- 退出 / 取消 / 待批准（submit 在 stream.py StreamingMixin）----

    def _cancel_turn(self) -> bool:
        """取消本轮（STREAMING/APPROVING）：Approving 先兜底解开待批准，再触发取消。"""
        if self.state == SessionState.APPROVING and self.pending is not None:
            req = self.pending
            self.pending = None
            if not req.respond.done():
                req.respond.set_result(Outcome.DENY_ONCE)
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            if self.turn_cancel is not None:
                self.turn_cancel.set()
            return True
        return False

    def action_quit_app(self) -> None:
        """Ctrl+C：流式/待批准态取消本轮（不退出）；否则退出程序。"""
        if self._cancel_turn():
            return
        if self._stream_task is not None:
            self._stream_task.cancel()
        self.exit()

    def action_cancel_turn(self) -> None:
        """Esc：流式/待批准态取消本轮。"""
        self._cancel_turn()

    async def on_event(self, event) -> None:
        """补全菜单在按键转发给聚焦控件前拦截（等价真正的 capture phase）。

        docs/ch10 T12 假设 App._on_key 走 capture phase、先于 ChatInput 拿到按键，
        但 Textual 8.2.8 的 App.on_event 对 Key 直接 forward 给 focused 控件
        （app.py:4066），App._on_key 只在事件冒泡回来时执行——此时 ChatInput 的
        enter 已 stop 并提交（chat_input.py），菜单永远等不到回车。因此把补全拦截
        提到 App.on_event 的 not-is_forwarded 分支：菜单激活时消费，否则原样转发。
        """
        if (
            isinstance(event, events.Key)
            and not event.is_forwarded
            and self.state == SessionState.IDLE
            and await self._handle_completion_key(event)
        ):
            return  # 补全菜单消费了 up/down/escape/enter/tab（docs/ch10 T12）
        await super().on_event(event)

    async def _on_key(self, event) -> None:
        """全局按键：待批准菜单 + 会话恢复列表 + Shift+Tab 模式循环。"""
        if self.state == SessionState.APPROVING and self.pending is not None:
            if self._update_approving(event.key):
                event.stop()
                return
        if self.state == SessionState.RESUMING:
            # Enter 恢复选中项 / Esc 返回空闲；其余交回 OptionList 导航（docs/ch09 T14）
            if await handle_resume_key(self, event):
                event.stop()
                return
        if event.key == "shift+tab" and self.state == SessionState.IDLE:
            self._mode = Mode((int(self._mode) + 1) % 4)
            self.query_one("#log", RichLog).write(
                Text(f"已切换到 {self._mode} 权限模式（Shift+Tab 继续切换）", style="dim")
            )
            self._update_statusbar()
            event.stop()
            return
        await super()._on_key(event)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """输入框内容变化 → 刷新补全菜单（docs/ch10 T12 step 4）。"""
        if event.text_area.id == "chat-input":
            self._sync_completion_from_input()

    def _render_completion(self) -> None:
        """把补全菜单当前状态渲染到 #completion Static（docs/ch10 T13 step 3）。"""
        if not self.is_mounted:
            return
        self.query_one("#completion", Static).update(
            self.completion.render(self.size.width) if self.completion.active else ""
        )

    def _update_approving(self, key: str) -> bool:
        """待批准菜单按键：返回是否已处理。"""
        if key in ("up", "k"):
            self.approve_cursor = (self.approve_cursor - 1) % 3
            self._render_approving()
            return True
        if key in ("down", "j"):
            self.approve_cursor = (self.approve_cursor + 1) % 3
            self._render_approving()
            return True
        if key in ("1", "2", "3"):
            self.approve_cursor = int(key) - 1
            self._resolve_approval(_OUTCOME_BY_INDEX[self.approve_cursor])
            return True
        if key in ("enter", "space"):
            self._resolve_approval(_OUTCOME_BY_INDEX[self.approve_cursor])
            return True
        if key == "y":
            self._resolve_approval(Outcome.ALLOW_ONCE)
            return True
        if key in ("n", "d"):
            self._resolve_approval(Outcome.DENY_ONCE)
            return True
        return False

    def _render_approving(self) -> None:
        if self.pending is not None:
            self.query_one("#streaming", Static).update(
                approval_block(self.pending, self.approve_cursor)
            )

    def _resolve_approval(self, outcome: Outcome) -> None:
        if self.pending is not None:
            req = self.pending
            self.pending = None
            self.state = SessionState.STREAMING
            if not req.respond.done():
                req.respond.set_result(outcome)
            self._refresh_streaming()
