"""conversation 单测（docs/ch02 T6；ch03 T13 扩展工具回合）。"""

from mewcode.conversation import Conversation
from mewcode.llm import Message, ToolCall, ToolResult


def test_roundtrip():
    c = Conversation()
    c.add_user("hi")
    c.add_assistant("hello")
    assert len(c) == 2
    roles = [m.role for m in c.messages()]
    assert roles == ["user", "assistant"]
    assert c.messages()[0].content == "hi"


def test_messages_returns_copy():
    c = Conversation()
    c.add_user("a")
    msgs = c.messages()
    msgs.clear()
    assert len(c.messages()) == 1


def test_last_role():
    c = Conversation()
    assert c.last_role() == ""
    c.add_user("a")
    assert c.last_role() == "user"
    c.add_tool_results([ToolResult(tool_call_id="1", content="ok")])
    assert c.last_role() == "tool"
    c.add_assistant("done")
    assert c.last_role() == "assistant"


def test_tool_rounds():
    c = Conversation()
    c.add_user("hi")
    c.add_assistant_with_tool_calls(
        "let me check", [ToolCall(id="1", name="read_file", input='{"path": "x"}')]
    )
    c.add_tool_results([ToolResult(tool_call_id="1", content="ok")])
    c.add_assistant("done")
    msgs = c.messages()
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].tool_calls[0].name == "read_file"
    assert msgs[2].tool_results[0].content == "ok"


def test_replace_history_deep_copy():
    c = Conversation()
    c.add_user("old")
    msgs = [Message(role="user", content="a"), Message(role="assistant", content="b")]
    c.replace_history(msgs)
    # 修改原列表与内层内容，历史不被影响（深拷贝）
    msgs.append(Message(role="user", content="c"))
    msgs[0].content = "mutated"
    assert [m.content for m in c.messages()] == ["a", "b"]


def test_replace_history_empty():
    c = Conversation()
    c.add_user("a")
    c.replace_history(None)
    assert len(c.messages()) == 0
    c.replace_history([])
    assert c.messages() == []


# ---------- docs/ch09 T2：on_append / on_replace 回调 ----------


def test_callbacks_append_and_replace():
    appended: list[Message] = []
    replaced: list[list[Message]] = []
    c = Conversation(
        on_append=lambda m: appended.append(m),
        on_replace=lambda ms: replaced.append(list(ms)),
    )
    c.add_user("hi")
    c.add_assistant("ok")
    c.add_assistant_with_tool_calls("t", [ToolCall(id="1", name="echo", input="{}")])
    c.add_tool_results([ToolResult(tool_call_id="1", content="r")])
    assert len(appended) == 4
    assert [m.role for m in appended] == ["user", "assistant", "assistant", "tool"]
    # 回调对象就是进入历史的那一条
    assert appended[0].content == "hi"
    assert appended[3].tool_results[0].content == "r"

    c.replace_history([Message(role="user", content="x")])
    assert len(replaced) == 1
    assert [m.content for m in replaced[0]] == ["x"]


def test_no_callback_matches_previous_behavior():
    """不设回调：行为与 ch08 完全一致（回归）。"""
    c = Conversation()
    c.add_user("hi")
    c.add_assistant("ok")
    c.replace_history([Message(role="user", content="x")])
    assert [m.role for m in c.messages()] == ["user"]
    assert c.messages()[0].content == "x"


def test_from_messages():
    msgs = [
        Message(role="user", content="a"),
        Message(role="assistant", content="b"),
    ]
    seen: list[str] = []
    c = Conversation.from_messages(msgs, on_append=lambda m: seen.append(m.content))
    assert len(c.messages()) == 2
    # 列表级拷贝：外部 append 不影响会话
    msgs.append(Message(role="user", content="leak"))
    assert len(c.messages()) == 2
    # 后续 append 触发回调
    c.add_user("c")
    assert seen == ["c"]
