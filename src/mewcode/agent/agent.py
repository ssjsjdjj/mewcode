"""ReAct 循环编排 + 权限接入（docs/ch04 T6；ch06 T8；ch08 T26 运行时改造）。

模型自主多轮干活；每个工具调用在真正执行前穿过五层权限护栏
（黑名单 → 沙箱 → 规则 → 模式兜底 在 Engine.check；第五层人在回路由本模块编排）。

ch08 起 Agent 持有 SessionRuntime（上下文管理跨轮状态），run 入口持
_run_lock 串行 manage_context；流式请求抽成 `_stream_once`（yield 文本
增量，结果经 out 传出），保证 err 路径不改写 Conversation——紧急压缩可
安全 replace_history。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from mewcode import prompt
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ManageInput,
    ManageOutput,
    RecoveryState,
    TriggerKind,
    manage_context,
    new_session_context,
)
from mewcode.compact.const import AUTO_SAFETY_MARGIN, MANUAL_SAFETY_MARGIN, SUMMARY_RESERVE
from mewcode.compact.token import estimate_tokens, usage_anchor
from mewcode.conversation import Conversation
from mewcode.llm import (
    ROLE_USER,
    Message,
    Provider,
    PromptTooLongError,
    Request,
    System,
    ToolCall,
    ToolResult,
)
from mewcode.llm import Usage as LLMUsage
from mewcode.permission import Decision, Engine, Mode, Outcome
from mewcode.skills import Catalog, active_to_prompt_entries, catalog_to_prompt_items
from mewcode.tool import DEFAULT_TIMEOUT, Registry, Result, ToolDefinition
from mewcode.tool.deferred import Discovery

from .event import CompactEvent, CompactPhase
from .runtime import SessionRuntime

if TYPE_CHECKING:
    from mewcode.memory import Manager

# ---- 迭代、停止常量（内置，不可配）----

MAX_ITERATIONS: int = 25  # 迭代上限兜底（F2）
MAX_UNKNOWN_RUN: int = 3  # 连续「整轮只产生未知工具调用」的迭代数上限（F2）
PLAN_REMINDER_INTERVAL: int = 4  # 规划提醒完整版重复间隔（docs/ch05 F7）

# 停止/收尾提示文案——既作 Event(notice) 推给 UI，也作 ensure_assistant_tail 写入历史的兜底文本
NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"

# 显式记忆请求关键词（docs/ch09 F25）：命中即触发一次记忆更新
MEMORY_SIGNAL_KEYWORDS = ("记住", "记忆", "别忘", "remember", "memo")


def _has_memory_signal(msgs: list[Message]) -> bool:
    """检测最近一轮消息是否含显式记忆请求关键词（docs/ch09 F25 触发条件②）。"""
    return any(
        keyword in (m.content or "").lower() for m in msgs for keyword in MEMORY_SIGNAL_KEYWORDS
    )


class Phase(Enum):
    START = "start"  # 工具开始执行
    END = "end"  # 工具执行完毕


@dataclass
class ToolEvent:
    """一次工具调用的开始/结束（供 TUI 渲染工具行与结果摘要）。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Usage:
    """一轮请求的 token 用量（透传 llm.Usage 语义）。"""

    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class ApprovalRequest:
    """人在回路待批准请求（docs/ch06 F8）。TUI 拿到后须 set_result 才继续。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


@dataclass
class Event:
    """单轮闭环对外事件流元素，消费者据非默认字段分派渲染。"""

    text: str = ""  # 模型文本增量
    tool: ToolEvent | None = None  # 工具调用开始/结束
    approval: ApprovalRequest | None = None  # 人在回路待批准（Ask 时）
    usage: Usage | None = None  # 本轮 token 用量
    iter: int = 0  # >0：进入第 iter 轮迭代（进度提示）
    notice: str = ""  # 系统提示（停止原因等），仅 UI 展示，不入对话历史
    done: bool = False  # 本轮（整个 Loop）结束
    err: Exception | None = None  # 出错（不中断会话）
    compact: CompactEvent | None = None  # 上下文压缩状态事件（ch08 T29a）


class Agent:
    """持有 provider / 注册中心 / 权限引擎，执行 ReAct 循环。"""

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str = "",
        engine: Engine | None = None,
        *,
        runtime: SessionRuntime | None = None,
        instruction_text: str = "",
        memory_text: str = "",
        memory_manager: "Manager | None" = None,
        discovery: Discovery | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        # 延迟加载视图（docs/ch07 追加 T14）。未注入时自建一份——测试与独立使用
        # Agent 的场景照旧只传 registry，且自建视图的已发现集合恒为空（等价旧行为）。
        self._discovery = discovery or Discovery(registry)
        # ch09 注入的指令/记忆文本，随每轮稳定系统提示组装（docs/ch09 T12）
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        # 记忆管理器：Done 分支每 5 轮或显式请求时异步触发更新（docs/ch09 T15）
        self._mem_mgr = memory_manager
        from mewcode.permission import new_engine

        self._engine = engine or new_engine(".")[0]
        if runtime is None:
            # 测试等场景未注入 runtime 时构造空 runtime，压缩动作不触发或退化
            runtime = SessionRuntime(
                replacement=ContentReplacementState(),
                recovery=RecoveryState(),
                auto_tracking=CompactCircuitBreaker(),
                session=new_session_context("."),
                context_window=200000,
            )
        self.runtime = runtime
        # Skill Catalog（docs/ch11 T26）：非空时把「名字+描述」清单拼进稳定系统提示。
        # 用普通 setter 而不是链式 builder——本项目没有 AgentOption 那套构造器。
        self._catalog: Catalog | None = None
        # 用 asyncio.Lock 保证 run 与 run_force_compact 不并发
        self._run_lock = asyncio.Lock()

    # ---- Skill 接入（docs/ch11 T26）----

    def with_catalog(self, catalog: Catalog | None) -> None:
        """注入 Skill Catalog，供第一阶段清单注入。"""
        self._catalog = catalog

    def activate_skill(self, name: str, body: str) -> None:
        """把某个 Skill 的 SOP 钉到本会话的环境上下文（LoadSkill 工具调）。"""
        self.runtime.active_skills.activate(name, body)

    def clear_active_skills(self) -> None:
        self.runtime.active_skills.clear()

    def list_active_skills(self) -> list[str]:
        return self.runtime.active_skills.names()

    def _build_stable_prompt(self) -> str:
        """稳定系统提示：注入 MEWCODE.md 指令、Skill 清单、记忆索引（F21）。"""
        catalog_text = ""
        if self._catalog is not None:
            catalog_text = prompt.render_skills_catalog(catalog_to_prompt_items(self._catalog))
        return prompt.build_system_prompt(self._instruction_text, self._memory_text, catalog_text)

    async def summarize_for_fork(self, msgs: list[Message]) -> str:
        """为 `fork_context=full` 生成主对话摘要（docs/ch11 F28）。

        复用 ch09 的摘要管道（`compact.layer2.summarize_once`）。它只读
        `ManageInput.provider`，其余字段填本 runtime 的现值即可；摘要请求不更新
        用量锚点。异常向上抛，由 Executor 降级处理。
        """
        from mewcode.compact.layer2 import summarize_once

        in_ = ManageInput(
            conv=Conversation(),  # summarize_once 不读 conv
            provider=self._provider,
            model=self._provider.model,
            context_window=self.runtime.context_window,
            tool_defs=[],  # 摘要请求不带工具
            replacement=self.runtime.replacement,
            recovery=self.runtime.recovery,
            auto_tracking=self.runtime.auto_tracking,
            session=self.runtime.session,
            usage_anchor=self.runtime.usage_anchor,
            anchor_msg_len=self.runtime.anchor_msg_len,
            estimated_token=0,
            trigger=TriggerKind.AUTO,
        )
        return await summarize_once(in_, msgs)

    def _compose_env(self, env_base: str) -> str:
        """环境上下文 = 基础环境块 + 当前已激活 Skill 的 SOP（F22）。

        必须**每轮迭代**重算：同一轮里 LoadSkill 刚激活的 Skill 要在下一次请求
        就可见。基础环境块每轮 run 只采集一次（它要跑 git 子进程），这里只重拼后缀。
        """
        block = prompt.render_active_skills_block(
            active_to_prompt_entries(self.runtime.active_skills)
        )
        return f"{env_base}\n\n{block}" if block else env_base

    async def _stream_once(
        self,
        req: Request,
        cancel: asyncio.Event,
        out: list,
    ) -> AsyncIterator[Event]:
        """单次流式请求：yield 文本增量供 UI 渲染；结果写入 out（4 元组）。

        out 收 `(text, calls, usage, err)`：
          - err 来自 StreamEvent.err 或流内异常，统一交给 run 处理，这里不
            yield Event(err=...)；
          - cancel 中断时 err 置 None（run 依据 cancel.is_set() 判定收尾）；
          - 累加的 text 只在成功路径由 run 写回 Conversation（err 路径不改写，
            保持原子，紧急压缩可安全 replace_history）。
        注：async generator 不允许 return value（PEP 525），结果经 out 传出；
        run 完整消费本生成器后 out 必已填充。
        """
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        usage: LLMUsage | None = None
        err: Exception | None = None
        try:
            async for ev in self._provider.stream(req):
                if cancel.is_set():
                    break
                if ev.err is not None:
                    err = ev.err
                    break
                if ev.usage is not None:
                    usage = ev.usage
                if ev.tool_calls:
                    calls.extend(ev.tool_calls)
                if ev.text:
                    text_parts.append(ev.text)
                    yield Event(text=ev.text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            err = exc
        out.extend(["".join(text_parts), calls, usage, err])

    async def run(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event]:
        # 用 asyncio.Lock 保证 run 与 run_force_compact 不并发触发 manage_context；
        # 也省去 runtime 上的细粒度锁——asyncio 单线程 + 本锁已保证串行（T27）。
        async with self._run_lock:
            # 稳定系统提示 + 环境信息（docs/ch05 F2/F3）；git 采集走线程，不阻塞事件循环（N4）。
            # 环境块每轮 run 只采集一次；已激活 Skill 的后缀在循环内逐轮重拼（ch11 F22）。
            stable = self._build_stable_prompt()
            env = await asyncio.to_thread(
                prompt.gather_environment, self._version, self._provider.model
            )
            env_base = env.render()

            unknown_run = 0
            for it in range(1, MAX_ITERATIONS + 1):
                yield Event(iter=it)
                if cancel.is_set():
                    self._finish_cancelled(conv)
                    return

                # 迭代级一次性紧急压缩标志（docs/ch08 T29）：同一轮内只重试一次
                emergency_retried = False

                # 按 mode 选 defs：同一份列表既喂 ManageInput.tool_defs 也喂
                # Request.tools；不缓存到 Agent 字段（docs/ch08 T27）。延迟加载叠加
                # 在模式过滤之上：先按 mode 取子集，再滤掉「可延迟且未拉取」的
                # （docs/ch07 追加 F22）——每轮重算，因此上一轮 tool_search 拉到的
                # 工具下一轮就进来，本轮刚拉的则要等下一轮。
                defs = self._discovery.visible_definitions(plan_only=mode == Mode.PLAN)

                # 环境上下文逐轮重拼：同一轮内 LoadSkill 激活的 SOP 下次请求即生效
                env_text = self._compose_env(env_base)

                # 规划模式按轮次注入 reminder（docs/ch05 F7）
                reminder = ""
                if mode == Mode.PLAN:
                    full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                    reminder = prompt.plan_reminder(full)

                # 未加载工具的名字清单走同一条 reminder 通道（docs/ch07 追加 F15）：
                # 与 plan reminder 并列拼接而非互相覆盖；无可延迟工具时 manifest 为
                # None，reminder 逐字节等于历史行为（F23）。
                manifest = self._discovery.manifest()
                if manifest is not None:
                    block = prompt.system_reminder(manifest)
                    reminder = f"{reminder}\n{block}" if reminder else block

                # ---- 每轮请求前先走上下文管理（layer1 写回可能替换 conv 历史）----
                est = estimate_tokens(
                    self.runtime.usage_anchor,
                    conv.messages(),
                    self.runtime.anchor_msg_len,
                )
                in_ = ManageInput(
                    conv=conv,
                    provider=self._provider,
                    model=self._provider.model,
                    context_window=self.runtime.context_window,
                    tool_defs=defs,
                    replacement=self.runtime.replacement,
                    recovery=self.runtime.recovery,
                    auto_tracking=self.runtime.auto_tracking,
                    session=self.runtime.session,
                    usage_anchor=self.runtime.usage_anchor,
                    anchor_msg_len=self.runtime.anchor_msg_len,
                    estimated_token=est,
                    trigger=TriggerKind.AUTO,
                )
                # 自动路径：阈值未达不发任何 Compact 事件（layer1 是静默操作）
                will_summarize = (
                    est >= self.runtime.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
                )
                if will_summarize:
                    yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))
                try:
                    out = await manage_context(in_)
                    mc_err = None
                except Exception as e:  # noqa: BLE001
                    mc_err = e
                    out = ManageOutput(before_tokens=est, after_tokens=0)
                if will_summarize:
                    yield Event(
                        compact=CompactEvent(
                            phase=CompactPhase.AFTER_AUTO,
                            before=out.before_tokens,
                            after=out.after_tokens,
                            err=mc_err,
                        )
                    )
                if mc_err is not None:
                    yield Event(err=mc_err)
                    break

                req = Request(
                    messages=conv.messages(),
                    tools=defs,
                    system=System(stable=stable, environment=env_text),
                    reminder=reminder,
                )

                # ---- 单次流式请求：增量文本 yield，结果 (text, calls, usage, err) ----
                stream_out: list = []
                async for ev in self._stream_once(req, cancel, stream_out):
                    yield ev
                text, calls, usage, err = stream_out

                if cancel.is_set():
                    self._finish_cancelled(conv)
                    return
                if (
                    err is not None
                    and isinstance(err, PromptTooLongError)
                    and not emergency_retried
                ):
                    # PTL 说明 AUTO 层压缩后仍超出模型上下文：换 EMERGENCY 强制压缩，
                    # 然后按压缩后的历史重建请求重试一次（docs/ch08 T29）。
                    emg_in = ManageInput(
                        conv=conv,
                        provider=self._provider,
                        model=self._provider.model,
                        context_window=self.runtime.context_window,
                        tool_defs=defs,
                        replacement=self.runtime.replacement,
                        recovery=self.runtime.recovery,
                        auto_tracking=self.runtime.auto_tracking,
                        session=self.runtime.session,
                        usage_anchor=self.runtime.usage_anchor,
                        anchor_msg_len=self.runtime.anchor_msg_len,
                        estimated_token=est,
                        trigger=TriggerKind.EMERGENCY,
                    )
                    yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))
                    try:
                        emg_out = await manage_context(emg_in)
                        emg_err = None
                    except Exception as ferr:  # noqa: BLE001
                        emg_err = ferr
                        emg_out = ManageOutput(before_tokens=est, after_tokens=0)
                    yield Event(
                        compact=CompactEvent(
                            phase=CompactPhase.AFTER_EMERGENCY,
                            before=emg_out.before_tokens,
                            after=emg_out.after_tokens,
                            err=emg_err,
                        )
                    )
                    if emg_err is not None:
                        yield Event(err=emg_err)
                        break
                    # 紧急压缩后 anchor 重设为 0（压缩结果本身已含摘要/恢复附件）
                    self.runtime.usage_anchor = 0
                    self.runtime.anchor_msg_len = 0
                    est2 = estimate_tokens(0, conv.messages(), 0)
                    if est2 >= self.runtime.context_window - MANUAL_SAFETY_MARGIN:
                        # 压缩后仍触顶：不可恢复，上抛原始 PTL，不再发起第二次请求
                        yield Event(err=err)
                        self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                        return
                    emergency_retried = True
                    # 用压缩后的历史重建请求再试一次
                    req = Request(
                        messages=conv.messages(),
                        tools=defs,
                        system=System(stable=stable, environment=env_text),
                        reminder=reminder,
                    )
                    stream_out = []
                    async for ev in self._stream_once(req, cancel, stream_out):
                        yield ev
                    text, calls, usage, err = stream_out
                if err is not None:
                    yield Event(err=err)
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                    return

                if usage is not None:
                    yield Event(
                        usage=Usage(
                            usage.input_tokens,
                            usage.output_tokens,
                            usage.cache_write,
                            usage.cache_read,
                        )
                    )
                    # 主对话路径成功返回 usage 时更新 anchor（摘要请求不更新）：
                    # 记录当时的 usage 总量与 conv 长度，供下一轮 estimate_tokens 计算 tail
                    self.runtime.usage_anchor = usage_anchor(usage)
                    self.runtime.anchor_msg_len = conv.length()

                if not calls:
                    # 自然完成（F2-1）
                    final_text = text if text.strip() else "（模型未给出最终答复）"
                    if not text.strip():
                        yield Event(text=final_text)
                    conv.add_assistant(final_text)
                    self._maybe_update_memory(conv)
                    yield Event(done=True)
                    return

                conv.add_assistant_with_tool_calls(text, calls)
                unknown_run = unknown_run + 1 if self._all_unknown(calls) else 0

                out: dict = {}
                async for item in self._execute_batched(calls, mode, cancel, out):
                    yield item
                conv.add_tool_results(out["results"])

                if not out["completed"]:
                    # 执行中被取消：最高优先级终止
                    self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                    return

                if unknown_run >= MAX_UNKNOWN_RUN:
                    yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                    self._ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                    yield Event(done=True)
                    return

            # 触达迭代上限（F2-2）
            yield Event(notice=NOTICE_MAX_ITER)
            self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
            yield Event(done=True)

    async def run_force_compact(
        self, conv: Conversation, tool_defs: list[ToolDefinition]
    ) -> tuple[int, int]:
        """TUI 手动压缩入口（docs/ch08 T30）：`/compact` 时经 asyncio.create_task 调用。

        与 run 共用 _run_lock，保证不会与主循环并发触发 manage_context；tool_defs
        由调用方传入（与下一次 run 的 defs 一致，避免各自独立计算）；失败异常直接
        上抛，由 TUI 捕获展示。
        """
        async with self._run_lock:
            in_ = ManageInput(
                conv=conv,
                provider=self._provider,
                model=self._provider.model,
                context_window=self.runtime.context_window,
                tool_defs=tool_defs,
                replacement=self.runtime.replacement,
                recovery=self.runtime.recovery,
                auto_tracking=self.runtime.auto_tracking,
                session=self.runtime.session,
                usage_anchor=self.runtime.usage_anchor,
                anchor_msg_len=self.runtime.anchor_msg_len,
                estimated_token=estimate_tokens(
                    self.runtime.usage_anchor, conv.messages(), self.runtime.anchor_msg_len
                ),
                trigger=TriggerKind.MANUAL,
            )
            out = await manage_context(in_)
            return (out.before_tokens, out.after_tokens)

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        mode: Mode,
        cancel: asyncio.Event,
        out: dict,
    ) -> AsyncIterator[Event]:
        """保序分批并发执行（F5）+ 权限判定（docs/ch06 F6）。结果写入 out。"""
        n = len(calls)
        results: list[ToolResult | None] = [None] * n

        def fill_cancelled(start: int) -> None:
            for k in range(start, n):
                if results[k] is None:
                    results[k] = ToolResult(
                        tool_call_id=calls[k].id, content=NOTICE_CANCELLED, is_error=True
                    )

        i = 0
        while i < n:
            if cancel.is_set():
                fill_cancelled(i)
                out.update(results=results, completed=False)
                return
            if self._registry.is_read_only(calls[i].name):
                # 连续只读区间 [i, j)：先逐项权限检查（只读永不 Ask），并发执行
                j = i
                while j < n and self._registry.is_read_only(calls[j].name):
                    j += 1
                denied = [False] * n
                for k in range(i, j):
                    decision, reason = self._engine.check(mode, calls[k], True)
                    if decision == Decision.DENY:
                        results[k] = ToolResult(
                            tool_call_id=calls[k].id, content=reason, is_error=True
                        )
                        denied[k] = True
                for k in range(i, j):
                    yield Event(
                        tool=ToolEvent(
                            name=calls[k].name, args=calls[k].input[:80], phase=Phase.START
                        )
                    )

                async def run_one(k: int):
                    return await self._registry.execute(
                        calls[k].name, calls[k].input, DEFAULT_TIMEOUT
                    )

                to_gather = [k for k in range(i, j) if not denied[k]]
                batch = await asyncio.gather(*[run_one(k) for k in to_gather])
                for k, r in zip(to_gather, batch):
                    await self._record_file_read(calls[k], r)
                    results[k] = ToolResult(
                        tool_call_id=calls[k].id, content=r.content, is_error=r.is_error
                    )
                for k in range(i, j):
                    r = results[k]
                    yield Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            phase=Phase.END,
                            result=r.content,
                            is_error=r.is_error,
                        )
                    )
                i = j
            else:
                # 有副作用：串行单个（权限可能 Ask → 人在回路）
                call = calls[i]
                yield Event(tool=ToolEvent(name=call.name, args=call.input[:80], phase=Phase.START))
                decision, reason = self._engine.check(mode, call, False)
                if decision == Decision.DENY:
                    results[i] = ToolResult(tool_call_id=call.id, content=reason, is_error=True)
                elif decision == Decision.ALLOW:
                    r = await self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT)
                    await self._record_file_read(call, r)
                    results[i] = ToolResult(
                        tool_call_id=call.id, content=r.content, is_error=r.is_error
                    )
                else:  # ASK → 第五层人在回路
                    respond: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
                    yield Event(
                        approval=ApprovalRequest(
                            name=call.name, args=call.input[:80], reason=reason, respond=respond
                        )
                    )
                    try:
                        outcome = await respond
                    except asyncio.CancelledError:
                        fill_cancelled(i)
                        out.update(results=results, completed=False)
                        return
                    if outcome in (Outcome.ALLOW_ONCE, Outcome.ALLOW_FOREVER):
                        if outcome == Outcome.ALLOW_FOREVER:
                            try:
                                self._engine.persist_local_allow(call)
                            except Exception:  # noqa: BLE001 —— 仅记日志不阻断
                                pass
                        r = await self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT)
                        await self._record_file_read(call, r)
                        results[i] = ToolResult(
                            tool_call_id=call.id, content=r.content, is_error=r.is_error
                        )
                    else:  # DENY_ONCE
                        results[i] = ToolResult(
                            tool_call_id=call.id, content="用户拒绝了该操作", is_error=True
                        )
                r = results[i]
                yield Event(
                    tool=ToolEvent(
                        name=call.name, phase=Phase.END, result=r.content, is_error=r.is_error
                    )
                )
                i += 1

        out.update(results=results, completed=True)

    # ---- 辅助 ----

    async def _record_file_read(self, call: ToolCall, r: Result) -> None:
        """ReadFile 成功后把文件内容记入 recovery（docs/ch08 T28）。

        只在 read_file 且未出错时触发；必须在本轮 conv.add_tool_results 之前
        完成，下一轮 manage_context 才能看到记录。读盘走线程，不阻塞事件循环。
        """
        if call.name != "read_file" or r.is_error:
            return
        args = call.input
        if not isinstance(args, dict):
            return
        path = args.get("path")
        if not isinstance(path, str) or not path:
            return
        try:
            abs_path = str(Path(path).resolve())
        except OSError:
            return
        try:
            data = await asyncio.to_thread(Path(abs_path).read_bytes)
        except OSError:
            return
        self.runtime.recovery.record_file(abs_path, data.decode("utf-8", errors="replace"))

    def _all_unknown(self, calls: list[ToolCall]) -> bool:
        """全部调用都指向未注册工具才返回 True；混入任一已知工具视为有进展。"""
        return all(self._registry.get(call.name) is None for call in calls)

    def _ensure_assistant_tail(self, conv: Conversation, fallback: str) -> None:
        """若历史不以 assistant 文本回合收尾，补一个，保证角色交替合法（F6）。"""
        if conv.last_role() != "assistant":
            conv.add_assistant(fallback)

    def _finish_cancelled(self, conv: Conversation) -> None:
        """取消路径统一收尾（不 yield notice，generator 终结即视为本轮结束）。"""
        self._ensure_assistant_tail(conv, NOTICE_CANCELLED)

    def _extract_recent_turn(self, conv: Conversation) -> list[Message]:
        """提取最近一轮消息：从最后一条 user 消息到当前末尾（docs/ch09 F25）。"""
        msgs = conv.messages()
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == ROLE_USER:
                return msgs[i:]
        return msgs

    def _maybe_update_memory(self, conv: Conversation) -> None:
        """每 5 轮自然完成或显式记忆请求时，异步触发记忆更新（docs/ch09 F25）。

        用 asyncio.create_task 不阻塞主循环；更新失败由 Manager 内部记日志吞掉。
        """
        if self._mem_mgr is None:
            return
        self.runtime.turn_count += 1
        recent = self._extract_recent_turn(conv)
        if self.runtime.turn_count % 5 == 0 or _has_memory_signal(recent):
            asyncio.create_task(self._mem_mgr.update_async(recent))
