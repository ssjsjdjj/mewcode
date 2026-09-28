"""Agent Loop 事件消费、工具行渲染与计时（docs/ch04 T7）。"""

from __future__ import annotations

import asyncio
import time

from rich.text import Text
from textual.widgets import RichLog, Static

from mewcode.agent import Phase
from mewcode.hook import Event as HookEvent
from mewcode.tui import ChatInput, SessionState, ToolDisplay
from mewcode.tui.commands import format_compact_notice
from mewcode.tui.view import (
    error_block,
    notice_block,
    render_markdown,
    tool_line,
    tool_result_summary,
    user_block,
)


class StreamingMixin:
    """为 MewCodeApp 提供 Agent 事件消费、计时与回合收尾。"""

    async def submit(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        # / 命令分发（docs/ch10 T13）：命令路径不写 conv、不调 LLM
        if await self.dispatch_slash(stripped):
            self.input_area.text = ""
            self.completion.hide()
            self._render_completion()
            return
        if self.state != SessionState.IDLE or self._stream_task is not None:
            return

        # UserPromptSubmit 拦截（docs/ch12 T19/F32）：在写历史**之前**判定。
        # 被拦下时不消费输入框——用户改完还能直接重发，不用重打。
        if self.hook_engine is not None:
            result = await self.hook_engine.dispatch(
                HookEvent.USER_PROMPT_SUBMIT,
                self._hook_payload(HookEvent.USER_PROMPT_SUBMIT, prompt=stripped),
            )
            if result.injected_prompts:
                self.runtime.append_reminders(result.injected_prompts)
            if result.blocked:
                self._show_hook_block(result.blocking_hook_name, result.reason)
                return

        self.conv.add_user(stripped)
        await self._begin_turn(stripped)

    def _show_hook_block(self, hook_name: str, reason: str) -> None:
        """被 hook 拦下：在输入框上方显示原因，焦点留在输入框等用户改（F32）。"""
        self.query_one("#log", RichLog).write(error_block(f"[hook {hook_name}] {reason}"))
        self.input_area.focus()

    async def _begin_turn(self, notice: str) -> None:
        """开始一轮：复用会话级 Agent（docs/ch08 T32.5），不再每轮重建。"""
        self.query_one("#log", RichLog).write(user_block(notice))
        self.query_one("#chat-input", ChatInput).clear()
        self.cur_reply = ""
        self.iter = 0
        self.cur_tools = []
        self.turn_start = time.monotonic()
        self.turn_cancel = asyncio.Event()
        self.state = SessionState.STREAMING
        self._ensure_agent()
        self._stream_task = asyncio.create_task(
            self._consume_events(self.agent.run(self.conv, self._mode, self.turn_cancel))
        )
        self._timer = self.set_interval(0.1, self._tick)

    async def _consume_events(self, generator) -> None:
        try:
            async for ev in generator:
                if ev.compact is not None:
                    # 压缩状态事件优先渲染（docs/ch08 T34a F24a/F24b）
                    self.query_one("#log", RichLog).write(
                        notice_block(format_compact_notice(ev.compact))
                    )
                if ev.err is not None:
                    self._finish_with_error(ev.err)
                    return
                if ev.approval:
                    self.pending = ev.approval
                    self.approve_cursor = 0
                    self.state = SessionState.APPROVING
                    self._render_approving()
                if ev.tool:
                    if ev.tool.phase == Phase.START:
                        if self.cur_reply:
                            self.query_one("#log", RichLog).write(render_markdown(self.cur_reply))
                            self.cur_reply = ""
                        self.cur_tools.append(ToolDisplay(ev.tool.name, ev.tool.args))
                        self._refresh_streaming()
                    else:  # END —— 结束序==入队序，弹队首即对应工具
                        td = (
                            self.cur_tools.pop(0)
                            if self.cur_tools
                            else ToolDisplay(ev.tool.name, "")
                        )
                        self.query_one("#log", RichLog).write(tool_line(td.name, td.args))
                        self.query_one("#log", RichLog).write(
                            tool_result_summary(ev.tool.result, ev.tool.is_error)
                        )
                        self._refresh_streaming()
                if ev.usage is not None:
                    self.usage_in += ev.usage.input
                    self.usage_out += ev.usage.output
                    self._update_statusbar()
                if ev.notice:
                    self.query_one("#log", RichLog).write(Text(ev.notice, style="dim"))
                if ev.iter:
                    self.iter = ev.iter
                    self._refresh_streaming()
                if ev.text:
                    self.cur_reply += ev.text
                    self._refresh_streaming()
                if ev.done:
                    self._finish_with_assistant(self.cur_reply)
                    return
            # 循环自然结束（如取消路径无 done 事件）
            self._end_turn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._finish_with_error(exc)

    def _tick(self) -> None:
        if self.state == SessionState.STREAMING:
            elapsed = int(time.monotonic() - self.turn_start)
            iter_txt = f" · 第 {self.iter} 轮" if self.iter else ""
            if self.cur_tools:
                lines = "\n".join(f"● {td.name}({td.args}) Running…" for td in self.cur_tools)
                self.query_one("#streaming", Static).update(f"{lines}\n({elapsed}s{iter_txt})")
            else:
                self.query_one("#streaming", Static).update(f"Imagining… ({elapsed}s{iter_txt})")

    def _refresh_streaming(self) -> None:
        if self.cur_tools:
            lines = "\n".join(f"● {td.name}({td.args}) Running…" for td in self.cur_tools)
            self.query_one("#streaming", Static).update(lines)
        else:
            self.query_one("#streaming", Static).update(self.cur_reply)

    def _finish_with_assistant(self, reply: str) -> None:
        # 历史由 Agent 维护，此处只渲染
        self.query_one("#log", RichLog).write(render_markdown(reply))
        self._end_turn()

    def _finish_with_error(self, err: Exception) -> None:
        self.query_one("#log", RichLog).write(error_block(err))
        self._end_turn()

    def _end_turn(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._stream_task = None
        self.cur_reply = ""
        self.cur_tools = []
        self.iter = 0
        self.pending = None
        self.approve_cursor = 0
        self.turn_cancel = None
        self.query_one("#streaming", Static).update("")
        self.state = SessionState.IDLE
        self._update_statusbar()
        self.query_one("#chat-input", ChatInput).focus()
