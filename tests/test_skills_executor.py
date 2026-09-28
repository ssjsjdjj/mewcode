"""Skill 执行器测试（docs/ch11 T19）：inline 注入、fork 子 Agent、失败降级、工具收窄。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mewcode.agent import SessionRuntime
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.llm import ROLE_USER, Message, Request, StreamEvent
from mewcode.llm import Usage as LLMUsage
from mewcode.permission import new_engine
from mewcode.skills import Catalog, Executor
from mewcode.tool import new_default_registry
from mewcode.command import NopUI


class FakeProvider:
    """按序吐出脚本帧的假 provider；`received` 是请求捕获 spy。"""

    def __init__(self, texts: list[str] | None = None) -> None:
        self.received: list[Request] = []
        self._texts = list(texts or ["子 Agent 的结论"])
        self.fail: Exception | None = None

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request):
        self.received.append(req)
        if self.fail is not None:
            yield StreamEvent(err=self.fail)
            return
        text = self._texts.pop(0) if self._texts else "再想想"
        yield StreamEvent(text=text)
        yield StreamEvent(usage=LLMUsage(input_tokens=10, output_tokens=5))
        yield StreamEvent(done=True)


class FakeUI(NopUI):
    """记录注入与回流；提供 fork 需要的会话消息。"""

    def __init__(self, messages: list[Message] | None = None) -> None:
        self.injections: list[tuple[str, str]] = []
        self.appended: list[str] = []
        self.errors: list[str] = []
        self._messages = list(messages or [])

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        self.injections.append((display_label, preset_prompt))

    def append_assistant_message(self, text: str) -> None:
        self.appended.append(text)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def cwd(self) -> str:
        return "."

    def recent_messages(self, n: int) -> list[Message]:
        return list(self._messages[-n:])

    def all_messages(self) -> list[Message]:
        return list(self._messages)


def runtime() -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


def write_skill(work: Path, name: str, frontmatter: str, body: str = "SOP 正文") -> None:
    d = work / ".mewcode" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def build(
    tmp_path, home, provider, *, main_agent=None, rt=None
) -> tuple[Executor, Catalog, SessionRuntime]:
    work = tmp_path / "work"
    catalog = Catalog.load(work)
    rt = rt or runtime()
    engine, _ = new_engine(str(tmp_path))
    ex = Executor(
        catalog,
        new_default_registry(),
        engine,
        "test",
        rt,
        provider=provider,
        main_agent=main_agent,
    )
    return ex, catalog, rt


# ---- inline ----


async def test_inline_injects_rendered_body(tmp_path, home):
    write_skill(
        tmp_path / "work",
        "commit",
        "name: commit\ndescription: 提交\nallowed_tools: [bash]\nmode: inline",
        "先看 git status",
    )
    ex, _, _ = build(tmp_path, home, FakeProvider())
    ui = FakeUI()
    await ex.execute("commit", "", ui)

    assert len(ui.injections) == 1
    label, prompt = ui.injections[0]
    assert label == "/commit"
    assert "先看 git status" in prompt
    assert "This skill is designed to use only these tools: bash." in prompt
    assert ui.appended == []  # inline 不走回流


async def test_unknown_skill_reports_error(tmp_path, home):
    ex, _, _ = build(tmp_path, home, FakeProvider())
    ui = FakeUI()
    await ex.execute("nope", "", ui)
    assert ui.errors == ["skill not found: nope"]
    assert ui.injections == []


# ---- fork ----


async def test_fork_appends_assistant_message(tmp_path, home):
    write_skill(
        tmp_path / "work",
        "review",
        "name: review\ndescription: 审查\nmode: fork\nfork_context: none",
    )
    provider = FakeProvider(["审查结论：没有问题"])
    ex, _, _ = build(tmp_path, home, provider)
    ui = FakeUI()
    await ex.execute("review", "", ui)

    assert ui.appended == ["审查结论：没有问题"]
    assert ui.injections == []  # fork 不注入主对话


async def test_fork_sub_agent_conv_is_isolated(tmp_path, home):
    """fork_context=none：子 Agent 看不到主对话历史（F28）。"""
    write_skill(tmp_path / "work", "review", "name: review\ndescription: d\nmode: fork")
    provider = FakeProvider()
    main_msgs = [
        Message(role=ROLE_USER, content="主对话里的秘密"),
        Message(role="assistant", content="知道了"),
    ]
    ex, _, _ = build(tmp_path, home, provider)
    await ex.execute("review", "", FakeUI(main_msgs))

    sub_msgs = provider.received[0].messages
    assert len(sub_msgs) == 1
    assert "主对话里的秘密" not in sub_msgs[0].content
    assert "SOP 正文" in sub_msgs[0].content


async def test_fork_recent_copies_tail(tmp_path, home):
    """fork_context=recent：带末尾 5 条，且是深拷贝（改子对话不污染主对话）。"""
    write_skill(
        tmp_path / "work",
        "review",
        "name: review\ndescription: d\nmode: fork\nfork_context: recent",
    )
    provider = FakeProvider()
    main_msgs = [Message(role=ROLE_USER, content=f"第{i}条") for i in range(8)]
    ex, _, _ = build(tmp_path, home, provider)
    await ex.execute("review", "", FakeUI(main_msgs))

    sub_msgs = provider.received[0].messages
    assert [m.content for m in sub_msgs[:-1]] == [f"第{i}条" for i in range(3, 8)]
    assert "SOP 正文" in sub_msgs[-1].content
    # 深拷贝：子对话的 Message 对象与原列表不是同一批
    assert sub_msgs[0] is not main_msgs[3]


async def test_fork_full_prefixes_summary(tmp_path, home):
    """fork_context=full：摘要作为首条 user 消息前缀（F28）。"""

    class StubAgent:
        def __init__(self) -> None:
            self.seen: list = []

        async def summarize_for_fork(self, msgs):
            self.seen.append(list(msgs))
            return "这是主对话的摘要"

    write_skill(
        tmp_path / "work",
        "review",
        "name: review\ndescription: d\nmode: fork\nfork_context: full",
    )
    provider = FakeProvider()
    stub = StubAgent()
    ex, _, _ = build(tmp_path, home, provider, main_agent=stub)
    await ex.execute("review", "", FakeUI([Message(role=ROLE_USER, content="早先的话")]))

    sub_msgs = provider.received[0].messages
    assert len(stub.seen) == 1
    assert "这是主对话的摘要" in sub_msgs[0].content
    assert "早先的话" not in sub_msgs[0].content  # 只给摘要，不给原文
    assert "SOP 正文" in sub_msgs[-1].content


async def test_fork_full_summary_failure_falls_back_to_recent(tmp_path, home, capsys):
    class BoomAgent:
        async def summarize_for_fork(self, msgs):
            raise RuntimeError("摘要炸了")

    write_skill(
        tmp_path / "work",
        "review",
        "name: review\ndescription: d\nmode: fork\nfork_context: full",
    )
    provider = FakeProvider()
    ex, _, _ = build(tmp_path, home, provider, main_agent=BoomAgent())
    ui = FakeUI([Message(role=ROLE_USER, content="早先的话")])
    await ex.execute("review", "", ui)

    assert ui.appended == ["子 Agent 的结论"]  # 仍然跑完
    assert "falling back to recent" in capsys.readouterr().err
    assert "早先的话" in provider.received[0].messages[0].content


async def test_fork_narrows_tools_to_allowed_tools(tmp_path, home):
    """子 Agent 的工具集被 allowed_tools 收窄（F28/F30）。"""
    write_skill(
        tmp_path / "work",
        "review",
        "name: review\ndescription: d\nmode: fork\nallowed_tools: [read_file, grep]",
    )
    provider = FakeProvider()
    ex, _, _ = build(tmp_path, home, provider)
    await ex.execute("review", "", FakeUI())

    names = [d.name for d in provider.received[0].tools]
    assert names == ["read_file", "grep"]


async def test_fork_with_empty_allowed_tools_keeps_all(tmp_path, home):
    """空白名单 = 不再收窄（F30 第 5 步）。"""
    write_skill(tmp_path / "work", "review", "name: review\ndescription: d\nmode: fork")
    provider = FakeProvider()
    ex, _, _ = build(tmp_path, home, provider)
    await ex.execute("review", "", FakeUI())
    assert len(provider.received[0].tools) == 6


async def test_fork_failure_becomes_assistant_text(tmp_path, home):
    """子 Agent 出错 → 回流一条 [skill X failed: ...] 文本，主对话不卡（N7）。"""
    write_skill(tmp_path / "work", "review", "name: review\ndescription: d\nmode: fork")
    provider = FakeProvider()
    provider.fail = RuntimeError("模型挂了")
    ex, _, _ = build(tmp_path, home, provider)
    ui = FakeUI()
    await ex.execute("review", "", ui)

    assert len(ui.appended) == 1
    assert ui.appended[0].startswith("[skill review failed:")
    assert "模型挂了" in ui.appended[0]


async def test_fork_usage_rolls_into_main_anchor(tmp_path, home):
    """fork 烧掉的 token 计入主 runtime 锚点（N6/AC16）。"""
    write_skill(tmp_path / "work", "review", "name: review\ndescription: d\nmode: fork")
    rt = runtime()
    rt.usage_anchor = 1000
    provider = FakeProvider()
    ex, _, _ = build(tmp_path, home, provider, rt=rt)
    await ex.execute("review", "", FakeUI())

    # 子 Agent 一轮 10+5=15
    assert rt.usage_anchor == 1015


async def test_fork_sub_runtime_is_separate(tmp_path, home):
    """子 Agent 用自己的 runtime，不覆盖主 runtime 的其它字段（隔离）。"""
    write_skill(tmp_path / "work", "review", "name: review\ndescription: d\nmode: fork")
    rt = runtime()
    rt.turn_count = 7
    provider = FakeProvider()
    ex, _, _ = build(tmp_path, home, provider, rt=rt)
    await ex.execute("review", "", FakeUI())

    assert rt.turn_count == 7  # 未被子的 run 改动
    assert rt.anchor_msg_len == 0  # 主对话长度没变，保持不变


async def test_execute_rereads_body_from_disk(tmp_path, home):
    """执行时重读 SKILL.md，用户改了就生效（N5）。"""
    write_skill(tmp_path / "work", "commit", "name: commit\ndescription: d\nmode: inline", "旧正文")
    ex, _, _ = build(tmp_path, home, FakeProvider())
    ui = FakeUI()
    await ex.execute("commit", "", ui)
    assert "旧正文" in ui.injections[0][1]

    p = tmp_path / "work" / ".mewcode" / "skills" / "commit" / "SKILL.md"
    p.write_text(
        "---\nname: commit\ndescription: d\nmode: inline\n---\n\n新正文\n", encoding="utf-8"
    )
    ui2 = FakeUI()
    await ex.execute("commit", "", ui2)
    assert "新正文" in ui2.injections[0][1]


async def test_executor_satisfies_skill_runner_protocol(tmp_path, home):
    """Executor 能直接当 command 包的 SkillRunner 用（结构性子类型）。"""
    ex, _, _ = build(tmp_path, home, FakeProvider())
    ui = FakeUI()
    await ex.execute("commit", "", ui)  # 内置 commit 是 inline
    assert len(ui.injections) == 1
    assert ui.injections[0][0] == "/commit"


async def test_builtin_review_is_fork(tmp_path, home):
    """内置 review 走 fork 分支（AC3）。"""
    provider = FakeProvider(["审查报告"])
    ex, _, _ = build(tmp_path, home, provider)
    ui = FakeUI()
    await ex.execute("review", "", ui)
    assert ui.appended == ["审查报告"]
    assert ui.injections == []
