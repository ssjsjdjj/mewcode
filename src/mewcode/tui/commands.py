"""UI Protocol 实现（docs/ch10 T9）：MewCodeApp 混入 CommandMixin。

ch08 保留项：CompactDone + format_compact_notice（stream.py _consume_events 与
app.on_compact_done 仍在使用；docs/ch10 T9a 的"全部移除"对这两项不适用）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual.message import Message
from textual.widgets import OptionList, RichLog

from mewcode import compact
from mewcode.agent import CompactEvent, CompactPhase
from mewcode.command.command import Kind
from mewcode.command.dispatch import parse
from mewcode.command.ui import SkillSummary
from mewcode.conversation import Conversation
from mewcode.llm import Message as LLMMessage  # 勿与 textual.message.Message 混名
from mewcode.permission import Mode
from mewcode.session import Writer, list_sessions
from mewcode.tui import ChatInput, SessionState
from mewcode.tui.resume import SessionItem
from mewcode.tui.view import error_block, notice_block, render_markdown


class CompactDone(Message):
    """手动 /compact 完成回投主循环（ch08 保留，docs/ch08 T33/T34a）。"""

    def __init__(self, event: CompactEvent) -> None:
        super().__init__()
        self.event = event


def format_compact_notice(ev: CompactEvent) -> str:
    """压缩状态文案：自动/紧急/手动三路径统一（ch08 T34a 保留）。"""
    if ev.phase == CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if ev.phase == CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if ev.err is not None:
        return f"压缩失败：{ev.err}"
    return f"已压缩，token 从 {ev.before} 降至 {ev.after}"


class CommandMixin:
    """UI Protocol 实现（docs/ch10 T9a/T9b）：供 command 包 handler 调用。

    只依赖 App 自身属性，不持有 Textual 组件引用；渲染输出先收集到
    _pending_println，由 dispatch_slash 统一刷新（F10）。
    """

    # ---- T9a 只读查询 ----

    def mode(self) -> Mode:
        return self._mode

    def usage_in(self) -> int:
        return self._usage_in

    def usage_out(self) -> int:
        return self._usage_out

    def model_name(self) -> str:
        return self.provider.model if self.provider is not None else ""

    def cwd(self) -> str:
        return self._cwd

    def tool_count(self) -> int:
        return self.tool_registry.count() if self.tool_registry is not None else 0

    def memory_files(self) -> list[str]:
        if self.mem_mgr is None:
            return []
        project, user = self.mem_mgr.list_files()
        return project + user

    def session_path(self) -> str:
        return self.writer.path if self.writer is not None else ""

    def session_id(self) -> str:
        return (
            self.runtime.session.session_id
            if self.runtime is not None and self.runtime.session is not None
            else ""
        )

    def idle(self) -> bool:
        return self.state == SessionState.IDLE

    @property
    def input_area(self) -> ChatInput:
        """当前输入框（docs/ch10 T11 的 _execute_selected / T13 的 submit 共用）。"""
        return self.query_one("#chat-input", ChatInput)

    # ---- T9b 写方法 ----

    def println(self, msg: str) -> None:
        self._pending_println.append(msg)

    def error(self, msg: str) -> None:
        self._pending_println.append(f"ERROR\x00{msg}")

    def set_mode(self, m: Mode) -> None:
        self._mode = m

    def quit(self) -> None:
        self.exit()

    def force_compact(self) -> None:
        if self.agent is None:
            self.error("压缩失败：Agent 尚未初始化")
            return
        # 走 App 的统一口径（docs/ch07 追加 T15）：手动压缩的 tool_defs 必须与
        # Agent 主循环一致，否则两次压缩的 token 估算对不上。
        defs = self.visible_tool_defs()
        self._pending_println.append(
            format_compact_notice(CompactEvent(phase=CompactPhase.BEFORE_AUTO))
        )
        asyncio.create_task(self._run_force_compact(defs))

    async def _run_force_compact(self, defs) -> None:
        before = after = 0
        err: Exception | None = None
        try:
            before, after = await self.agent.run_force_compact(self.conv, defs)
        except Exception as exc:  # noqa: BLE001
            err = exc
        self.post_message(
            CompactDone(
                CompactEvent(phase=CompactPhase.AFTER_AUTO, before=before, after=after, err=err)
            )
        )

    def open_resume_menu(self) -> None:
        """打开历史会话列表（docs/ch10 T10：原 resume.begin_resume 主体迁入）。

        state guard 已由 dispatch_slash 按 Kind 统一处理，这里直接填充列表并切换
        到 RESUMING；Textual 组件交互均为同步，无需 create_task。
        """
        select = self.query_one("#select", OptionList)
        select.clear_options()
        items = list_sessions(self.sessions_dir)
        self.resume_items = items
        for info in items:
            select.add_option(SessionItem(info).display_text)
        select.action_first()
        self.state = SessionState.RESUMING

    async def clear_and_new_session(self) -> None:
        """结束当前会话并开启新会话（docs/ch10 T9b F17/N9，旧存档保留可 /resume）。

        ch12 起改 async：需要在旧会话关闭前 `await` SessionEnd 的 hook 分派
        （docs/ch12 T20），并清掉引擎的 only_once 集合（N5）。顺序：SessionEnd →
        关旧 writer → 换新会话 → SessionStart，这样 hook 看到的是各自时刻的真实状态。
        """
        await self._dispatch_session_end()
        if self.writer is not None:
            self.writer.close()
        try:
            new_ses_ctx = compact.new_session_context(self._cwd)
        except Exception as exc:  # noqa: BLE001
            self.error(str(exc))
            return
        try:
            new_writer = Writer(new_ses_ctx.session_dir)
        except Exception as exc:  # noqa: BLE001
            self.error(str(exc))
            return
        self.writer = new_writer
        self.conv = self._bind_conversation(new_writer)
        self.ses_ctx = new_ses_ctx
        if self.runtime is not None:
            self.runtime.reset_for_new_session(new_ses_ctx)
        self.iter = 0
        self._usage_in = 0
        self._usage_out = 0
        # 已发现集合是会话内存态，新会话必须清空（docs/ch07 追加 F19/AC20）。
        # 放在新会话建立之后：与 /resume「不重置」的次序形成对照，两处都靠位置说话。
        if self.discovery is not None:
            self.discovery.reset()
        # only_once 是会话态，换会话即清空（docs/ch12 F27/N5）
        if self.hook_engine is not None:
            await self.hook_engine.reset_for_new_session()
        self.query_one("#log", RichLog).clear()
        await self._dispatch_session_start()
        self._update_statusbar()

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        """提示词命令：追加 user 消息并触发回合（docs/ch10 T9b F11）。

        _begin_turn 内部已用 user_block 渲染 notice，这里传原始字符串避免双重包装。
        """
        self.conv.add_user(preset_prompt)
        asyncio.create_task(self._begin_turn(display_label))

    # ---- Skill 相关（docs/ch11 T27，UI 协议扩展 N11）----

    def list_catalog_skills(self) -> list[SkillSummary]:
        if self.catalog is None:
            return []
        return [
            SkillSummary(s.meta.name, s.meta.description, str(s.source), s.meta.mode)
            for s in self.catalog.list()
        ]

    def list_active_skills(self) -> list[str]:
        if self.runtime is None:
            return []
        return self.runtime.active_skills.names()

    def clear_active_skills(self) -> None:
        if self.runtime is not None:
            self.runtime.active_skills.clear()

    def append_assistant_message(self, text: str) -> None:
        """fork 回流：把子 Agent 的结论作为一条 assistant 消息写进主对话（F29）。

        走 `Conversation.add_assistant` 而非自己拼消息，这样 writer 的 on_append
        会自动把它落进会话 JSONL（用户角度看就是一条普通回复）。这里额外把它
        渲染进 scrollback——fork 不经过 `_begin_turn`，没人替它写日志区。
        """
        self.conv.add_assistant(text)
        self.query_one("#log", RichLog).write(render_markdown(text))

    def recent_messages(self, n: int) -> list[LLMMessage]:
        return self.conv.messages()[-n:] if n > 0 else []

    def all_messages(self) -> list[LLMMessage]:
        return self.conv.messages()

    # ---- Hook 查询（docs/ch12 T21）----

    def hook_sources(self) -> list[str]:
        return list(self.hook_engine.sources) if self.hook_engine is not None else []

    def hook_rules(self) -> list[Any]:
        return list(self.hook_engine.rules) if self.hook_engine is not None else []

    def _bind_conversation(self, writer: Writer) -> Conversation:
        on_append = writer.on_append if writer is not None else None
        on_replace = writer.on_replace if writer is not None else None
        return Conversation(on_append=on_append, on_replace=on_replace)

    # ---- T9c 分发 ----

    async def dispatch_slash(self, text: str) -> bool:
        """分发 / 命令；非命令形态返回 False（docs/ch10 T9c）。"""
        name, is_slash = parse(text)
        if not is_slash:
            return False
        self._pending_println.clear()
        cmd = self.cmd_registry.lookup(name) if self.cmd_registry is not None else None
        if cmd is None:
            # 退化输入（纯 / 或 /<空白>）不拼接名字，避免"未知命令: /, ..."悬空斜杠
            self._pending_println.append("未知命令: 输入 /help 查看可用命令")
        elif cmd.kind in (Kind.UI, Kind.PROMPT) and self.state != SessionState.IDLE:
            self._pending_println.append("请等待当前任务完成")
        else:
            try:
                await cmd.handler(self)
            except Exception as exc:  # noqa: BLE001
                self._pending_println.append(f"ERROR\x00{exc}")
        self._flush_pending()
        return True

    def _flush_pending(self) -> None:
        """把 _pending_println 内每条按 ERROR 前缀分流渲染到 scrollback。"""
        log = self.query_one("#log", RichLog)
        for item in self._pending_println:
            if item.startswith("ERROR\x00"):
                log.write(error_block(item[len("ERROR\x00") :]))
            else:
                log.write(notice_block(item))
        self._pending_println.clear()
