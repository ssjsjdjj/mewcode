"""agent ReAct 循环测试（docs/ch04 T6）：场景 A-F。"""

import asyncio
import tempfile

from mewcode.agent import (
    Agent,
    CompactPhase,
    MAX_ITERATIONS,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    SessionRuntime,
)
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.permission import Mode, Outcome, new_engine
from mewcode.conversation import Conversation
from mewcode.llm import (
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    ToolResult,
    Usage as LLMUsage,
)
from mewcode.tool import Registry, Result, new_default_registry


class FakeProvider:
    """按调用次数弹出预置 StreamEvent；脚本耗尽后恒返工具调用（迭代上限场景）。

    摘要请求（content 含 [conversation]）同样按调用序消耗脚本帧，并计入
    summarize_calls；帧内无 usage 且最后一帧为 done 时自动补一条 Usage，让
    主对话路径能更新锚点。
    """

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = 0
        self.summarize_calls = 0
        self.received: list[Request] = []

    @property
    def name(self):
        return "fake"

    @property
    def model(self):
        return "m"

    async def stream(self, req: Request):
        self.calls += 1
        self.received.append(req)
        content = req.messages[0].content if req.messages else ""
        if "[conversation]" in content:
            self.summarize_calls += 1
        idx = self.calls - 1
        if idx < len(self._scripts):
            frames = self._scripts[idx]
            has_usage = any(ev.usage is not None for ev in frames)
            for i, ev in enumerate(frames):
                if ev.done and i == len(frames) - 1 and not has_usage:
                    yield StreamEvent(usage=LLMUsage(input_tokens=1, output_tokens=1))
                yield ev
        else:
            yield StreamEvent(
                tool_calls=[ToolCall(id=f"x{self.calls}", name="echo", input="{}")],
                usage=LLMUsage(input_tokens=1, output_tokens=1),
            )


class EchoTool:
    def __init__(self):
        self.executions = 0

    def name(self):
        return "echo"

    def description(self):
        return "echo tool"

    def parameters(self):
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self):
        return False

    async def execute(self, args):
        self.executions += 1
        return Result(content="ok")


def _test_runtime() -> SessionRuntime:
    """测试用临时 runtime：session 落在系统临时目录，不污染项目 .mewcode。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


async def run_agent(
    provider, registry=None, mode=Mode.BYPASS, cancel=None, version="dev", engine=None
):
    registry = registry or new_default_registry()
    agent = Agent(provider, registry, version, engine, runtime=_test_runtime())
    conv = Conversation()
    conv.add_user("任务")
    cancel = cancel or asyncio.Event()
    events = [ev async for ev in agent.run(conv, mode, cancel)]
    return events, conv


def echo_registry() -> Registry:
    r = Registry()
    r.register(EchoTool())
    return r


# ---------- 场景 A：多轮链路（AC1） ----------


async def test_multi_round_chain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="2", name="write_file", input='{"path": "b.txt", "content": "hi"}'
                        )
                    ]
                )
            ],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    events, conv = await run_agent(provider)
    iters = [e.iter for e in events if e.iter]
    assert iters == [1, 2, 3]
    assert any(e.tool for e in events)
    final_text = "".join(e.text for e in events)
    assert "完成" in final_text
    assert [m.role for m in conv.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


# ---------- 场景 B：迭代上限（AC3） ----------


async def test_iteration_limit():
    provider = FakeProvider([])  # 恒返工具调用 → 永不自然完成
    registry = echo_registry()
    events, conv = await run_agent(provider, registry=registry)
    notices = [e.notice for e in events if e.notice]
    assert notices == [NOTICE_MAX_ITER]
    assert provider.calls == MAX_ITERATIONS
    assert conv.last_role() == "assistant"


# ---------- 场景 C：连续未知工具（AC4） ----------


async def test_unknown_tools_stop():
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[ToolCall(id="1", name="nope", input="{}")])],
            [StreamEvent(tool_calls=[ToolCall(id="2", name="nope", input="{}")])],
            [StreamEvent(tool_calls=[ToolCall(id="3", name="nope", input="{}")])],
        ]
    )
    registry = Registry()  # 空 → 全部未知
    events, conv = await run_agent(provider, registry=registry)
    notices = [e.notice for e in events if e.notice]
    assert notices == [NOTICE_UNKNOWN_TOOLS]
    assert conv.last_role() == "assistant"


async def test_unknown_reset_on_known():
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[ToolCall(id="1", name="nope", input="{}")])],
            [StreamEvent(tool_calls=[ToolCall(id="2", name="echo", input="{}")])],
            [StreamEvent(tool_calls=[ToolCall(id="3", name="nope", input="{}")])],
            [StreamEvent(tool_calls=[ToolCall(id="4", name="nope", input="{}")])],
            [StreamEvent(text="停")],
        ]
    )
    registry = echo_registry()
    events, conv = await run_agent(provider, registry=registry)
    notices = [e.notice for e in events if e.notice]
    assert notices == []  # 已知工具重置计数 → 自然完成
    assert conv.last_role() == "assistant"


# ---------- 场景 D：保序分批并发（AC8） ----------


class ConcurrencyTracker:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.read_finish: list[float] = []
        self.rw_start: float | None = None


def make_batch_registry(tracker):
    class ReadTool:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

        def description(self):
            return "read-only"

        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        @property
        def read_only(self):
            return True

        async def execute(self, args):
            tracker.active += 1
            tracker.peak = max(tracker.peak, tracker.active)
            await asyncio.sleep(0.05)
            tracker.active -= 1
            tracker.read_finish.append(asyncio.get_event_loop().time())
            return Result(content=f"{self._name}-ok")

    class WriteTool:
        def name(self):
            return "write"

        def description(self):
            return "side-effect"

        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        @property
        def read_only(self):
            return False

        async def execute(self, args):
            tracker.rw_start = asyncio.get_event_loop().time()
            return Result(content="write-ok")

    r = Registry()
    r.register(ReadTool("ro1"))
    r.register(ReadTool("ro2"))
    r.register(WriteTool())
    return r


async def test_ordered_batched_concurrency():
    tracker = ConcurrencyTracker()
    registry = make_batch_registry(tracker)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="ro1", input="{}"),
                        ToolCall(id="2", name="ro2", input="{}"),
                        ToolCall(id="3", name="write", input="{}"),
                    ]
                )
            ],
            [StreamEvent(text="好了")],
        ]
    )
    events, conv = await run_agent(provider, registry=registry)
    assert tracker.peak >= 2  # 两只读确实并发
    assert tracker.rw_start is not None
    last_read_finish = max(tracker.read_finish)
    assert tracker.rw_start >= last_read_finish  # 有副作用工具在只读之后开始
    # 结果按原始调用序回灌
    results = conv.messages()[-2].tool_results
    assert [r.content for r in results] == ["ro1-ok", "ro2-ok", "write-ok"]


# ---------- 场景 E：取消历史一致（AC9） ----------


async def test_cancel_history_consistent():
    class BlockingTool:
        def name(self):
            return "block"

        def description(self):
            return "blocking"

        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        @property
        def read_only(self):
            return False

        async def execute(self, args):
            await asyncio.sleep(0.3)
            return Result(content="blocked-done")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="block", input="{}"),
                        ToolCall(id="2", name="echo", input="{}"),
                    ]
                )
            ],
            [StreamEvent(text="不会到达")],
        ]
    )
    registry = Registry()
    registry.register(BlockingTool())
    registry.register(EchoTool())
    cancel = asyncio.Event()
    agent = Agent(provider, registry, runtime=_test_runtime())
    conv = Conversation()
    conv.add_user("任务")

    async def consume():
        return [ev async for ev in agent.run(conv, Mode.BYPASS, cancel)]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.15)  # 第一个工具（block）执行中
    cancel.set()
    await task

    roles = [m.role for m in conv.messages()]
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_results = conv.messages()[-2].tool_results
    assert tool_results[0].content == "blocked-done"
    assert tool_results[1].is_error and NOTICE_CANCELLED in tool_results[1].content
    assert conv.last_role() == "assistant"


# ---------- 场景 F：Plan 工具集（AC13） ----------


async def test_plan_mode_tools_and_suffix():
    provider = FakeProvider(
        [[StreamEvent(text="计划如下：\n1. 读文件\n2. 写实现"), StreamEvent(done=True)]]
    )
    registry = new_default_registry()
    events, conv = await run_agent(provider, registry=registry, mode=Mode.PLAN)
    req = provider.received[0]
    assert [d.name for d in req.tools] == ["read_file", "glob", "grep"]
    assert "PLAN MODE" in req.reminder
    assert req.system.stable  # 稳定系统提示非空
    assert req.system.environment  # 环境段非空
    assert conv.last_role() == "assistant"


# ---------- docs/ch05：Request 装配 / 按轮次 reminder / 缓存透传 / reminder 不入历史 ----------


async def test_reminder_per_round_in_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a"}')])],
            [StreamEvent(tool_calls=[ToolCall(id="2", name="read_file", input='{"path": "b"}')])],
            [StreamEvent(text="计划完成")],
        ]
    )
    events, conv = await run_agent(provider, mode=Mode.PLAN)
    reqs = provider.received
    assert len(reqs) >= 2
    assert "<system-reminder>" in reqs[0].reminder
    assert "must NOT" in reqs[0].reminder  # iter1 完整提醒
    assert "must NOT" not in reqs[1].reminder  # iter2 精简提醒
    # reminder 不写入持久历史
    all_text = " ".join(m.content for m in conv.messages())
    assert "<system-reminder>" not in all_text


async def test_stable_system_same_across_modes():
    normal = FakeProvider([[StreamEvent(text="好"), StreamEvent(done=True)]])
    plan = FakeProvider([[StreamEvent(text="好"), StreamEvent(done=True)]])
    await run_agent(normal, mode=Mode.DEFAULT)
    await run_agent(plan, mode=Mode.PLAN)
    assert normal.received[0].system.stable == plan.received[0].system.stable


async def test_tools_by_mode():
    normal = FakeProvider([[StreamEvent(text="好"), StreamEvent(done=True)]])
    plan = FakeProvider([[StreamEvent(text="好"), StreamEvent(done=True)]])
    registry = new_default_registry()
    await run_agent(normal, registry=registry, mode=Mode.DEFAULT)
    await run_agent(plan, registry=registry, mode=Mode.PLAN)
    all_names = [d.name for d in normal.received[0].tools]
    plan_names = [d.name for d in plan.received[0].tools]
    assert set(all_names) == {"read_file", "write_file", "edit_file", "bash", "glob", "grep"}
    assert set(plan_names) == {"read_file", "glob", "grep"}


async def test_cache_usage_passthrough():
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    usage=LLMUsage(
                        input_tokens=10, output_tokens=5, cache_write=100, cache_read=200
                    )
                ),
                StreamEvent(text="ok"),
                StreamEvent(done=True),
            ]
        ]
    )
    events, conv = await run_agent(provider)
    usages = [e.usage for e in events if e.usage]
    assert len(usages) == 1
    assert usages[0].cache_write == 100
    assert usages[0].cache_read == 200


# ---------- docs/ch06：权限集成 ----------


def make_engine(root):
    engine, err = new_engine(str(root))
    assert err is None
    return engine


async def test_deny_fed_back_loop_continues(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = make_engine(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path":"/etc/passwd"}')]
                )
            ],
            [StreamEvent(text="抱歉，改用项目内文件"), StreamEvent(done=True)],
        ]
    )
    events, conv = await run_agent(provider, mode=Mode.DEFAULT, engine=engine)
    tool_msgs = [m for m in conv.messages() if m.tool_results]
    assert tool_msgs and tool_msgs[0].tool_results[0].is_error
    assert "项目目录之外" in tool_msgs[0].tool_results[0].content
    assert conv.last_role() == "assistant"


async def test_mixed_batch_ordered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.txt").write_text("x")
    engine = make_engine(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="read_file", input='{"path":"/etc/passwd"}'),
                        ToolCall(id="2", name="read_file", input='{"path":"ok.txt"}'),
                    ]
                )
            ],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    events, conv = await run_agent(provider, mode=Mode.DEFAULT, engine=engine)
    results = conv.messages()[-2].tool_results
    assert results[0].tool_call_id == "1" and results[0].is_error
    assert results[1].tool_call_id == "2" and not results[1].is_error


async def _approval_round(tmp_path, outcome):
    engine = make_engine(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="write_file", input='{"path":"a.txt","content":"x"}')
                    ]
                )
            ],
            [StreamEvent(text="写好了"), StreamEvent(done=True)],
        ]
    )
    agent = Agent(provider, new_default_registry(), "dev", engine, runtime=_test_runtime())
    conv = Conversation()
    conv.add_user("写文件")
    cancel = asyncio.Event()
    approvals = []
    async for ev in agent.run(conv, Mode.DEFAULT, cancel):
        if ev.approval:
            approvals.append(ev.approval)
            ev.approval.respond.set_result(outcome)
    return approvals, conv, engine


async def test_approval_allow_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    approvals, conv, _ = await _approval_round(tmp_path, Outcome.ALLOW_ONCE)
    assert len(approvals) == 1
    assert (tmp_path / "a.txt").exists()
    assert conv.last_role() == "assistant"


async def test_approval_deny_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    approvals, conv, _ = await _approval_round(tmp_path, Outcome.DENY_ONCE)
    assert len(approvals) == 1
    assert not (tmp_path / "a.txt").exists()
    tool = [m for m in conv.messages() if m.tool_results][0]
    assert tool.tool_results[0].is_error
    assert conv.last_role() == "assistant"


async def test_approval_forever_writes_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    approvals, conv, engine = await _approval_round(tmp_path, Outcome.ALLOW_FOREVER)
    assert (tmp_path / "a.txt").exists()
    local = (tmp_path / ".mewcode" / "settings.local.yaml").read_text(encoding="utf-8")
    assert "Write(a.txt)" in local


async def test_read_only_no_approval_and_denied_in_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    engine = make_engine(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="read_file", input='{"path":"a.txt"}'),
                        ToolCall(id="2", name="read_file", input='{"path":"/etc/passwd"}'),
                    ]
                )
            ],
            [StreamEvent(text="好"), StreamEvent(done=True)],
        ]
    )
    events, conv = await run_agent(provider, mode=Mode.DEFAULT, engine=engine)
    assert not any(ev.approval for ev in events)  # 只读永不 Ask（并发不退化）
    results = conv.messages()[-2].tool_results
    assert results[0].tool_call_id == "1" and not results[0].is_error
    assert results[1].tool_call_id == "2" and results[1].is_error


async def test_cancel_during_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = make_engine(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="write_file", input='{"path":"a.txt","content":"x"}')
                    ]
                )
            ],
            [StreamEvent(text="不会到达")],
        ]
    )
    agent = Agent(provider, new_default_registry(), "dev", engine, runtime=_test_runtime())
    conv = Conversation()
    conv.add_user("写")
    cancel = asyncio.Event()

    async def consume():
        events = []
        async for ev in agent.run(conv, Mode.DEFAULT, cancel):
            events.append(ev)
        return events

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # 让 approval 发出
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    roles = [m.role for m in conv.messages()]
    assert roles[-1] == "assistant"  # 历史以 assistant 收尾，合法


# ---------- ch08 T29a：Compact 状态事件 ----------


def test_runtime_reset_for_new_session():
    """reset_for_new_session：跨轮状态清零、session 替换、context_window 保留。"""
    runtime = _test_runtime()
    old_replacement, old_recovery, old_tracking = (
        runtime.replacement,
        runtime.recovery,
        runtime.auto_tracking,
    )
    runtime.replacement._seen_ids.add("x")
    runtime.recovery._files["f"] = None  # type: ignore[assignment]
    runtime.auto_tracking._consecutive_failures = 3
    runtime.usage_anchor = 123
    runtime.anchor_msg_len = 7
    runtime.turn_count = 3
    new_ctx = new_session_context(tempfile.mkdtemp())

    runtime.reset_for_new_session(new_ctx)

    assert runtime.session is new_ctx
    assert runtime.usage_anchor == 0
    assert runtime.anchor_msg_len == 0
    assert runtime.turn_count == 0
    assert runtime.replacement._seen_ids == set()
    assert runtime.recovery._files == {}
    assert runtime.auto_tracking._consecutive_failures == 0
    assert runtime.replacement is not old_replacement  # 子状态整体换新
    assert runtime.recovery is not old_recovery
    assert runtime.auto_tracking is not old_tracking
    assert runtime.context_window == 200000  # 配置保留，不随会话重置


def _small_runtime(context_window: int = 40000) -> SessionRuntime:
    """小窗口 runtime：让测试用较小对话历史就能越过自动压缩阈值。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=context_window,
    )


async def test_agent_emits_auto_compact_events():
    # 大工具结果让 layer1 落盘（estimated_token 越过阈值 → 发 BEFORE/AFTER_AUTO）；
    # layer1 后 token 回落，layer2 不会真的发摘要请求，脚本只需主对话一帧。
    provider = FakeProvider([[StreamEvent(text="ok"), StreamEvent(done=True)]])
    agent = Agent(provider, new_default_registry(), "dev", runtime=_small_runtime())
    conv = Conversation()
    conv.add_user("任务")
    conv.add_assistant_with_tool_calls("", [ToolCall(id="1", name="echo", input="{}")])
    conv.add_tool_results([ToolResult(tool_call_id="1", content="x" * 60000, is_error=False)])
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    compacts = [ev.compact for ev in events if ev.compact is not None]
    assert [c.phase for c in compacts] == [
        CompactPhase.BEFORE_AUTO,
        CompactPhase.AFTER_AUTO,
    ]
    assert compacts[1].before > compacts[1].after
    assert compacts[1].err is None
    assert any(ev.done for ev in events)  # 主对话正常完成


async def test_agent_emits_emergency_compact_events():
    # 第 1 次 stream 直接 PTL → 触发 EMERGENCY 压缩（发 BEFORE/AFTER_EMERGENCY）+
    # 摘要请求一帧 + 重试成功，run 正常完成。
    provider = FakeProvider(
        [
            [StreamEvent(err=PromptTooLongError("too long"))],
            [StreamEvent(text="<summary>压缩摘要</summary>")],
            [StreamEvent(text="ok"), StreamEvent(done=True)],
        ]
    )
    agent = Agent(provider, new_default_registry(), "dev", runtime=_test_runtime())
    conv = Conversation()
    conv.add_user("任务")
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    compacts = [ev.compact for ev in events if ev.compact is not None]
    assert [c.phase for c in compacts] == [
        CompactPhase.BEFORE_EMERGENCY,
        CompactPhase.AFTER_EMERGENCY,
    ]
    assert compacts[1].err is None
    assert any(ev.done for ev in events)  # 重试后正常完成


# ---------- ch08 T31：紧急压缩单元测试 ----------


async def test_agent_emergency_compact_succeeds():
    # 第 1 次 stream PTL → 摘要请求一帧 → 重试原请求正常完成 → 整体成功
    provider = FakeProvider(
        [
            [StreamEvent(err=PromptTooLongError("too long"))],
            [StreamEvent(text="<summary>压缩摘要</summary>")],
            [StreamEvent(text="好的"), StreamEvent(done=True)],
        ]
    )
    events, conv = await run_agent(provider)
    assert provider.summarize_calls == 1
    assert any(ev.done for ev in events)
    assert conv.last_role() == "assistant"  # 历史以 assistant 收尾
    assert "好的" in [m.content for m in conv.messages() if m.content]


async def test_agent_emergency_compact_re_raise_on_second_ptl():
    # 紧急压缩后的重试仍 PTL → 上抛异常，不再发起第三次请求
    provider = FakeProvider(
        [
            [StreamEvent(err=PromptTooLongError("first"))],
            [StreamEvent(text="<summary>压缩摘要</summary>")],
            [StreamEvent(err=PromptTooLongError("second"))],
        ]
    )
    events, conv = await run_agent(provider)
    errs = [ev.err for ev in events if ev.err is not None]
    assert len(errs) == 1
    assert isinstance(errs[0], PromptTooLongError)
    assert provider.calls == 3  # 重试后再 PTL，不发起第三次
    assert not any(ev.done for ev in events)


async def test_agent_emergency_compact_unrecoverable_when_still_too_big():
    # 紧急压缩后重新估算仍 ≥ cw - MANUAL_SAFETY_MARGIN → 不发起第二次 stream，
    # 直接上抛原始 PTL
    provider = FakeProvider(
        [
            [StreamEvent(err=PromptTooLongError("too long"))],
            [StreamEvent(text="<summary>压缩摘要</summary>")],
        ]
    )
    agent = Agent(provider, new_default_registry(), "dev", runtime=_small_runtime(10000))
    conv = Conversation()
    conv.add_user("x" * 30000)  # 压缩后仍在近期原文里，est2 依旧触顶
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    errs = [ev.err for ev in events if ev.err is not None]
    assert len(errs) == 1
    assert isinstance(errs[0], PromptTooLongError)
    assert provider.calls == 2  # 主对话 PTL + 摘要请求，无重试请求
