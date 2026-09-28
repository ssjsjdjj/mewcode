"""端到端 + F24 token 实测（docs/ch07 追加 T16；AC21–AC27）。

跑法：`pytest tests/test_ch07_deferred_e2e.py -s`（-s 才能看到对照表）。

合成 fixture：4 个虚拟 server × 15 个工具 + 6 个内置 = 66 个工具，全部本地构造，
不连真 server、不发网络。测量口径见文末两条局限声明。
"""

from __future__ import annotations

import asyncio
import json
import tempfile

from mewcode import prompt
from mewcode.agent import Agent, SessionRuntime
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.compact.const import ESTIMATE_CHARS_PER_TOKEN
from mewcode.conversation import Conversation
from mewcode.llm import Request, StreamEvent, ToolCall, Usage as LLMUsage
from mewcode.permission import Mode
from mewcode.session import Writer, list_sessions
from mewcode.tool import Registry, Result, new_default_registry
from mewcode.tool.deferred import Discovery
from mewcode.tool.tool_search import ToolSearchTool
from mewcode.tui.app import MewCodeApp
from mewcode.tui.resume import do_resume_session

from test_tui import cfg, FakeProvider

SERVER_COUNT = 4
TOOLS_PER_SERVER = 15
BUILTIN_COUNT = 6
ALL_TOOLS = BUILTIN_COUNT + SERVER_COUNT * TOOLS_PER_SERVER  # 66


def _full_name(server: int, index: int) -> str:
    return f"mcp__srv{server}__tool{index:02d}"


class SynthMcpTool:
    """合成的 MCP 工具：形状、描述长度与真实 MCP 工具同量级，全部延迟加载。"""

    def __init__(self, server: int, index: int) -> None:
        self._name = _full_name(server, index)
        self._server = server
        self._index = index
        # 偶数索引只读、奇数索引可写：Plan Mode 的端到端场景靠这条区分
        self._read_only = index % 2 == 0

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return (
            f"（合成工具）在第 {self._server} 号服务的第 {self._index} 号资源上执行操作。"
            f"支持按条件过滤、分页读取与结果排序；调用前请确认目标资源存在，"
            f"失败时返回结构化错误而不是抛异常。此工具为 {self._name}。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "目标资源标识"},
                "filter": {"type": "string", "description": "过滤条件表达式"},
                "limit": {"type": "integer", "description": "返回条数上限"},
                "offset": {"type": "integer", "description": "分页偏移"},
                "dry_run": {"type": "boolean", "description": "只做校验不落盘"},
            },
            "required": ["target"],
        }

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def deferrable(self) -> bool:
        return True

    async def execute(self, args: str) -> Result:
        return Result(content=f"{self._name} ok")


def _synth_registry() -> tuple[Registry, Discovery, ToolSearchTool]:
    """66 个工具的注册中心 + 视图 + tool_search（与 cli.py 的装配顺序一致）。"""
    registry = new_default_registry()
    for server in range(SERVER_COUNT):
        for index in range(TOOLS_PER_SERVER):
            registry.register(SynthMcpTool(server, index))
    discovery = Discovery(registry)
    tool_search = ToolSearchTool(discovery)
    registry.register(tool_search)
    return registry, discovery, tool_search


class _ScriptedProvider:
    """按调用序弹出预置帧；脚本耗尽后直接结束。"""

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self._scripts = list(scripts)
        self.calls = 0
        self.received: list[Request] = []

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "m"

    async def stream(self, req: Request):
        self.calls += 1
        self.received.append(req)
        idx = self.calls - 1
        frames = self._scripts[idx] if idx < len(self._scripts) else [StreamEvent(done=True)]
        for i, ev in enumerate(frames):
            if ev.done and i == len(frames) - 1 and ev.usage is None:
                yield StreamEvent(usage=LLMUsage(input_tokens=1, output_tokens=1))
            yield ev


def _runtime() -> SessionRuntime:
    """测试用临时 runtime：session 落系统临时目录，不污染项目 .mewcode。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


async def _run(provider, registry, mode=Mode.BYPASS, discovery=None):
    """跑一轮完整闭环，返回 (events, conv)。

    `discovery` 必须与 `tool_search` 持有的那一份是**同一个对象**——这正是 cli.py
    的装配方式。不传也能跑（Agent 会按 registry 自建一份），但那份自建视图与
    tool_search 里的视图各自记着不同的已发现集合，拉取动作就传不到主循环，
    端到端断言会以「拉了但不出现」的形式失败。
    """
    agent = Agent(provider, registry, "dev", runtime=_runtime(), discovery=discovery)
    conv = Conversation()
    conv.add_user("任务")
    events = [ev async for ev in agent.run(conv, mode, asyncio.Event())]
    return events, conv


def _select_call(seq: int, name: str) -> StreamEvent:
    """模型通过 tool_search 精确拉取一个工具。"""
    return StreamEvent(
        tool_calls=[
            ToolCall(
                id=str(seq), name="tool_search", input=json.dumps({"keyword": f"select:{name}"})
            )
        ]
    )


def _names(defs) -> list[str]:
    return [d.name for d in defs]


# ---------- 端到端（AC21–AC24） ----------


async def test_first_turn_injects_only_builtins_and_tool_search():
    registry, discovery, _ = _synth_registry()
    provider = _ScriptedProvider([[StreamEvent(text="好"), StreamEvent(done=True)]])
    await _run(provider, registry, Mode.BYPASS)

    first = provider.received[0]
    names = _names(first.tools)
    assert len(names) == BUILTIN_COUNT + 1  # 6 内置 + tool_search，60 个 MCP 工具全不在
    assert "tool_search" in names
    assert not any(n.startswith("mcp__") for n in names)
    # 名字清单走 reminder 通道，且覆盖全部 60 个未加载工具
    assert first.reminder.startswith("<system-reminder>")
    assert "tool_search" in first.reminder
    listed = {n for n in _manifest_names(first.reminder)}
    assert listed == {
        _full_name(s, i) for s in range(SERVER_COUNT) for i in range(TOOLS_PER_SERVER)
    }
    # 稳定系统段不含清单（F15：清单不进 system.stable）
    assert "mcp__srv0__tool00" not in first.system.stable


def _manifest_names(reminder: str) -> list[str]:
    return [
        line[2:]
        for line in reminder.splitlines()
        if line.startswith("- mcp__") or line.startswith("- 其他")
    ]


async def test_fetch_lands_in_next_turn_only():
    registry, discovery, _ = _synth_registry()
    target = _full_name(0, 0)
    provider = _ScriptedProvider(
        [
            [_select_call(1, target)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    await _run(provider, registry, Mode.BYPASS, discovery)

    assert target not in _names(provider.received[0].tools)  # 首轮不可见
    assert target in _names(provider.received[1].tools)  # 拉取后下一轮可见
    assert len(provider.received[1].tools) == BUILTIN_COUNT + 2
    # 拉走的工具从下一轮清单里消失，其余 59 个仍在
    assert target not in _manifest_names(provider.received[1].reminder)
    assert len(_manifest_names(provider.received[1].reminder)) == 59
    assert discovery.discovered_names() == [target]


async def test_select_miss_keeps_loop_alive():
    registry, discovery, _ = _synth_registry()
    provider = _ScriptedProvider(
        [
            [_select_call(1, "mcp__srv0__does_not_exist")],
            [StreamEvent(text="换关键词重试"), StreamEvent(done=True)],
        ]
    )
    events, conv = await _run(provider, registry, Mode.BYPASS, discovery)

    assert provider.calls == 2  # 未命中没有中断循环
    assert not [e for e in events if e.err]
    # 错误文本经既有工具结果通道回灌（角色为 tool），循环据此继续
    tool_msgs = [m for m in conv.messages() if m.role == "tool"]
    assert len(tool_msgs) == 1
    results = tool_msgs[0].tool_results
    assert len(results) == 1
    assert results[0].is_error is True
    assert "mcp__srv0__does_not_exist" in results[0].content
    assert any(e.text for e in events if e.text)


async def test_select_miss_result_is_error_text_not_crash():
    """未命中走的是结构化错误结果（AC19），由工具结果通道回灌给模型。"""
    registry, _, tool_search = _synth_registry()
    out = await tool_search.execute(json.dumps({"keyword": "select:mcp__srv0__nope"}))
    assert out.is_error is True
    assert "mcp__srv0__nope" in out.content


async def test_plan_mode_defers_and_hides_write_tools():
    registry, discovery, _ = _synth_registry()
    read_target = _full_name(0, 0)  # 偶数 → 只读
    write_target = _full_name(1, 1)  # 奇数 → 可写
    provider = _ScriptedProvider(
        [
            [_select_call(1, read_target)],
            [_select_call(2, write_target)],
            [StreamEvent(text="计划完成"), StreamEvent(done=True)],
        ]
    )
    await _run(provider, registry, Mode.PLAN, discovery)

    first = _names(provider.received[0].tools)
    assert "tool_search" in first  # 只读 → Plan Mode 下自身可见（F22）
    assert first == [n for n in first if not n.startswith("mcp__")]  # 首轮无 MCP 工具
    # 只读工具拉取后可见
    assert read_target in _names(provider.received[1].tools)
    # 可写工具即便拉取过，在 Plan Mode 下仍不可见（F22：先按模式过滤）
    assert write_target not in _names(provider.received[2].tools)


async def test_repeated_fetch_is_idempotent_end_to_end():
    registry, discovery, _ = _synth_registry()
    target = _full_name(2, 4)
    provider = _ScriptedProvider(
        [
            [_select_call(1, target)],
            [_select_call(2, target)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    await _run(provider, registry, Mode.BYPASS, discovery)
    assert discovery.discovered_names() == [target]
    assert _names(provider.received[2].tools) == _names(provider.received[1].tools)


async def test_keyword_search_end_to_end():
    registry, discovery, _ = _synth_registry()
    provider = _ScriptedProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="tool_search", input=json.dumps({"keyword": "srv3"}))
                    ]
                )
            ],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    await _run(provider, registry, Mode.BYPASS, discovery)
    assert len(discovery.discovered_names()) == 5  # 上限 5（F18）
    hits = [n for n in _names(provider.received[1].tools) if n.startswith("mcp__")]
    assert hits == discovery.discovered_names()


async def test_fetched_tool_is_actually_called_and_result_returns():
    """场景 10 的后半段：拉到之后真调用它，结果回灌、模型续答（不连真 server）。"""
    registry, discovery, _ = _synth_registry()
    target = _full_name(0, 0)
    provider = _ScriptedProvider(
        [
            [_select_call(1, target)],
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="2", name=target, input=json.dumps({"target": "x"}))]
                )
            ],
            [StreamEvent(text="根据结果，结论是……"), StreamEvent(done=True)],
        ]
    )
    events, conv = await _run(provider, registry, Mode.BYPASS, discovery)

    assert provider.calls == 3
    results = [r for m in conv.messages() if m.role == "tool" for r in m.tool_results]
    assert [r.tool_call_id for r in results] == ["1", "2"]  # 拉取 + 真调用各一条
    assert results[0].is_error is False  # 拉取成功
    assert results[1].is_error is False  # 调用成功
    assert f"{target} ok" in results[1].content  # 合成工具的返回值
    assert "结论是" in "".join(e.text for e in events if e.text)


# ---------- 场景 12：/clear 清空、/resume 保留（AC20/F19） ----------


async def test_clear_resets_and_resume_keeps_discovery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # _cwd 在 __init__ 取，必须chdir 之后再构造 App
    registry, discovery, _ = _synth_registry()
    ses_ctx = new_session_context(str(tmp_path))
    writer = Writer(ses_ctx.session_dir)
    old_conv = Conversation(on_append=writer.on_append, on_replace=writer.on_replace)
    old_conv.add_user("历史消息")
    writer.close()
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=ses_ctx,
        context_window=200000,
    )
    app = MewCodeApp(
        [cfg()],
        provider=FakeProvider(),
        registry=registry,
        runtime=runtime,
        discovery=discovery,
    )
    target = _full_name(0, 0)

    async with app.run_test():
        # /clear：新会话的已发现集合为空，首轮又只剩名字清单
        discovery.select(target)
        await app.clear_and_new_session()
        assert discovery.discovered_names() == []
        assert target not in _names(app.visible_tool_defs())

        # /resume：恢复同一进程内的旧会话，已发现集合保持在当前值（不被清空）
        discovery.select(target)
        info = next(i for i in list_sessions(app.sessions_dir) if i.id == ses_ctx.session_id)
        await do_resume_session(app, info)
        assert discovery.discovered_names() == [target]
        assert target in _names(app.visible_tool_defs())


async def test_status_counts_registered_total_not_visible(tmp_path, monkeypatch):
    """N10：/status 报注册总数，不因延迟而变化——拉取前后都是 67。"""
    monkeypatch.chdir(tmp_path)
    registry, discovery, _ = _synth_registry()
    app = MewCodeApp(
        [cfg()],
        provider=FakeProvider(),
        registry=registry,
        runtime=_runtime(),
        discovery=discovery,
    )
    async with app.run_test():
        before = app.tool_count()
        assert before == ALL_TOOLS + 1  # 66 + tool_search
        discovery.select(_full_name(0, 0))
        assert app.tool_count() == before
        assert len(app.visible_tool_defs()) == BUILTIN_COUNT + 2  # 本轮注入数远小于总数


# ---------- F23/AC25：无可延迟工具时逐字节不变 ----------


async def test_no_deferrable_reminder_is_byte_identical():
    """无 MCP 时 reminder 与改动前逐字节相同：非 Plan 为空串，Plan 就是 plan_reminder。"""
    registry = new_default_registry()  # 只有 6 个内置，全部不可延迟
    assert len(registry.definitions()) == BUILTIN_COUNT

    plain = _ScriptedProvider([[StreamEvent(text="x"), StreamEvent(done=True)]])
    await _run(plain, registry, Mode.BYPASS)
    assert plain.received[0].reminder == ""

    planning = _ScriptedProvider([[StreamEvent(text="x"), StreamEvent(done=True)]])
    await _run(planning, registry, Mode.PLAN)
    assert planning.received[0].reminder == prompt.plan_reminder(full=True)
    assert "tool_search" not in _names(plain.received[0].tools)


async def test_no_deferrable_request_matches_pre_change_assembly():
    """AC23/AC25 的字面口径：无 MCP 时 `tools` 序列化与「改动前的组装方式」逐字节相同。"""
    registry = new_default_registry()

    plain = _ScriptedProvider([[StreamEvent(text="x"), StreamEvent(done=True)]])
    await _run(plain, registry, Mode.BYPASS)
    # 改动前：tools = registry.definitions()、reminder = ""（非 Plan）
    assert _wire(plain.received[0].tools) == _wire(registry.definitions())
    assert plain.received[0].reminder == ""

    planning = _ScriptedProvider([[StreamEvent(text="x"), StreamEvent(done=True)]])
    await _run(planning, registry, Mode.PLAN)
    # 改动前：tools = registry.read_only_definitions()、reminder = plan_reminder
    assert _wire(planning.received[0].tools) == _wire(registry.read_only_definitions())
    assert planning.received[0].reminder == prompt.plan_reminder(full=True)


async def test_manifest_is_appended_beside_plan_reminder():
    """有可延迟工具时两条 reminder 并列拼接，plan reminder 不被清单顶掉。"""
    registry, discovery, _ = _synth_registry()
    provider = _ScriptedProvider([[StreamEvent(text="x"), StreamEvent(done=True)]])
    await _run(provider, registry, Mode.PLAN, discovery)

    reminder = provider.received[0].reminder
    assert reminder.startswith(prompt.plan_reminder(full=True))  # 前半段一字不改
    tail = reminder[len(prompt.plan_reminder(full=True)) :]
    assert tail.startswith("\n<system-reminder>")
    assert "tool_search" in tail
    assert reminder.count("<system-reminder>") == 2


# ---------- F24：token 实测（AC25–AC27） ----------


def _wire(defs) -> str:
    """按 provider 出网的形状序列化（anthropic_provider 的 tools 参数）。

    只含 name / description / input_schema 三字段——`deferrable` 是本地协议成员，
    永远不上线（AC26/N13）。这串文本同时用于 F24 计长与 F23 的逐字节比对。
    """
    payload = [
        {"name": d.name, "description": d.description, "input_schema": d.input_schema} for d in defs
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _wire_chars(defs) -> int:
    """口径 = 序列化字符数 ÷ ESTIMATE_CHARS_PER_TOKEN，复用压缩层的估算常量。"""
    return len(_wire(defs))


def _tokens(defs) -> int:
    return round(_wire_chars(defs) / ESTIMATE_CHARS_PER_TOKEN)


def _baseline_injection(registry) -> list:
    """「改动前」的注入集合：当时没有 tool_search，所以基线不含它。

    拿 67（含 tool_search）当基线会让改动后的首轮也白得一个工具，比较就不公平了。
    """
    return [d for d in registry.definitions() if d.name != "tool_search"]


def test_f24_measurement_prints_table(capsys):
    registry, discovery, _ = _synth_registry()

    full = _baseline_injection(registry)
    assert len(full) == ALL_TOOLS

    first = discovery.visible_definitions(plan_only=False)
    assert len(first) == BUILTIN_COUNT + 1

    for name in [_full_name(0, i) for i in range(5)]:
        discovery.select(name)
    after_5 = discovery.visible_definitions(plan_only=False)

    for name in [_full_name(1, i) for i in range(10)]:
        discovery.select(name)
    after_15 = discovery.visible_definitions(plan_only=False)

    rows = [
        ("全量注入（改动前）", full),
        ("延迟加载首轮", first),
        ("拉取 5 个后", after_5),
        ("拉取 15 个后", after_15),
    ]
    base = _tokens(full)
    lines = [
        "",
        "F24 实测（合成 fixture：4 server × 15 工具 + 6 内置 = 66 工具）",
        f"口径：tools 序列化字符数 ÷ {ESTIMATE_CHARS_PER_TOKEN}"
        f"（compact/const.py ESTIMATE_CHARS_PER_TOKEN）",
        "",
        f"{'场景':<20}{'工具数':>8}{'字符数':>10}{'估算 token':>12}{'相对全量':>10}",
        "-" * 62,
    ]
    for label, defs in rows:
        chars = _wire_chars(defs)
        tokens = _tokens(defs)
        ratio = f"{tokens / base * 100:.1f}%"
        lines.append(f"{label:<20}{len(defs):>8}{chars:>10}{tokens:>12}{ratio:>10}")
    lines += [
        "",
        "局限一：估算是「字符数 ÷ 3.5」的近似值，不是真实分词器计数；",
        "        真实 token 数随模型与分词器浮动，本表只用于同口径横向比较。",
        "局限二：fixture 是本地合成的，其描述与 schema 的长度是构造出来的，",
        "        不代表任何真实 MCP server 的工具集；绝对数值不可外推。",
        "",
    ]
    print("\n".join(lines))

    out = capsys.readouterr().out
    assert "F24 实测" in out
    assert "局限一" in out and "局限二" in out
    print(out, end="")  # readouterr 已经把表吃掉了，这里补一次让 `-s` 真能看到

    # 表里数字必须真的在下降，否则这张表没有意义
    assert _tokens(first) < _tokens(full)
    assert _tokens(first) + _tokens(after_5) < _tokens(after_5) * 2
    assert _tokens(after_5) <= _tokens(after_15) <= _tokens(full)
    assert _wire_chars(first) < _wire_chars(full) / 5


def test_f24_numbers_match_the_table_row_shapes():
    """对照表的每一行都对应一个可复算的可见集，防止数字与场景脱钩。"""
    registry, discovery, _ = _synth_registry()
    assert len(_baseline_injection(registry)) == ALL_TOOLS
    assert len(discovery.visible_definitions(plan_only=False)) == BUILTIN_COUNT + 1
    discovery.select(_full_name(0, 0))
    assert len(discovery.visible_definitions(plan_only=False)) == BUILTIN_COUNT + 2
