"""mcp/tool 模块单测（docs/ch07 T3）：命名拼接 / 禁用字符 / 适配字段 / Execute 各分支。"""

import asyncio
from typing import Any

import pytest
from mcp import types as mtypes

from mewcode.mcp import tool as tool_mod
from mewcode.mcp.tool import adapt_tool
from mewcode.tool import Result, Tool


class StubSession:
    """可编程 CallerSession：返回指定结果 / 抛异常 / 永久阻塞三种模式。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result: Any = None
        self._exc: BaseException | None = None
        self._block: asyncio.Event | None = None

    def returns(self, result: Any) -> "StubSession":
        self._result = result
        return self

    def raises(self, exc: BaseException) -> "StubSession":
        self._exc = exc
        return self

    def blocks(self) -> "StubSession":
        self._block = asyncio.Event()
        return self

    async def call_tool(self, name: str, arguments: Any) -> Any:
        self.calls.append((name, arguments))
        if self._block is not None:
            await self._block.wait()
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture(autouse=True)
def reset_warn_once():
    """清空模块级非 text 告警集合，保证每用例独立。"""
    tool_mod._non_text_warn_once.clear()
    yield
    tool_mod._non_text_warn_once.clear()


def make_tool(
    name: str = "echo",
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    annotations: mtypes.ToolAnnotations | None = None,
) -> mtypes.Tool:
    # 一律用协议原名（camelCase）构造：mcp ≤1.28 它是别名、1.29 起是唯一字段名，
    # 只有这个名字在两个版本上都合法（详见 mcp/tool.py 的 _sdk_field）。
    return mtypes.Tool.model_validate(
        {
            "name": name,
            "description": description or "",
            "inputSchema": input_schema if input_schema is not None else {"type": "object"},
            "annotations": annotations,
        }
    )


def text(text: str) -> mtypes.TextContent:
    return mtypes.TextContent(type="text", text=text)


def image_block() -> mtypes.ImageContent:
    """真实的非 TextContent 内容块（image），用于验证丢弃逻辑。"""
    return mtypes.ImageContent.model_validate(
        {"type": "image", "data": "aGk=", "mimeType": "image/png"}
    )


def call_result(content: list[Any], is_error: bool = False) -> mtypes.CallToolResult:
    return mtypes.CallToolResult.model_validate({"content": content, "isError": is_error})


def annotations(read_only: bool) -> mtypes.ToolAnnotations:
    return mtypes.ToolAnnotations.model_validate({"readOnlyHint": read_only})


def test_adapt_valid():
    t = make_tool(name="echo", description="echoes", input_schema={"type": "object", "x": 1})
    out = adapt_tool("github", t, StubSession())
    assert out is not None
    assert out.full_name == "mcp__github__echo"
    assert out.remote_name == "echo"
    assert out.name() == "mcp__github__echo"
    assert out.description() == "echoes"
    assert out.parameters() == {"type": "object", "x": 1}


def test_adapt_illegal_chars():
    t = make_tool(name="echo")
    assert adapt_tool("srv.with.dot", t, StubSession()) is None
    assert adapt_tool("ok", make_tool(name="echo@x"), StubSession()) is None
    assert adapt_tool("ok", make_tool(name="echo/x"), StubSession()) is None


def test_adapt_illegal_chars_warns(capsys):
    t = make_tool(name="bad.name")
    adapt_tool("srv", t, StubSession())
    assert "skip tool mcp__srv__bad.name" in capsys.readouterr().err


def test_adapt_description_fallback():
    t = make_tool(name="echo", description="")
    out = adapt_tool("demo", t, StubSession())
    assert out is not None
    assert "demo" in out.description() and "echo" in out.description()


def test_adapt_schema_none():
    out = adapt_tool("srv", make_tool(name="echo", input_schema=None), StubSession())
    assert out is not None
    assert out.parameters() == {"type": "object"}


def test_adapt_read_only_none_safe():
    out = adapt_tool("srv", make_tool(name="echo", annotations=None), StubSession())
    assert out is not None
    assert out.read_only is False


def test_adapt_read_only_hint():
    ann = annotations(True)
    out = adapt_tool("srv", make_tool(name="echo", annotations=ann), StubSession())
    assert out is not None
    assert out.read_only is True


def test_adapt_read_only_hint_false():
    ann = annotations(False)
    out = adapt_tool("srv", make_tool(name="echo", annotations=ann), StubSession())
    assert out is not None
    assert out.read_only is False


def test_conforms_to_tool_protocol():
    out = adapt_tool("srv", make_tool(name="echo"), StubSession())
    assert isinstance(out, Tool)


async def test_execute_success():
    stub = StubSession().returns(
        call_result([text("one"), text("two")], is_error=False)
    )
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute('{"a": 1}')
    assert isinstance(result, Result)
    assert result.content == "one\ntwo"
    assert result.is_error is False
    assert stub.calls == [("echo", {"a": 1})]


async def test_execute_no_args():
    stub = StubSession().returns(call_result([text("ok")], is_error=False))
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    await tool.execute("")
    assert stub.calls == [("echo", None)]
    await tool.execute("{}")
    assert stub.calls == [("echo", None), ("echo", None)]


async def test_execute_remote_error():
    stub = StubSession().returns(call_result([text("boom")], is_error=True))
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute("{}")
    assert result.is_error is True
    assert result.content == "boom"


async def test_execute_raises_protocol_error():
    stub = StubSession().raises(ValueError("connection reset"))
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute("{}")
    assert result.is_error is True
    assert "MCP 工具调用失败" in result.content


async def test_execute_timeout(monkeypatch):
    monkeypatch.setattr(tool_mod, "call_timeout", 0.2)
    stub = StubSession().blocks()
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute("{}")
    assert result.is_error is True
    assert "超时" in result.content


async def test_execute_bad_json_no_call():
    stub = StubSession().returns(call_result([], is_error=False))
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute("{oops")
    assert result.is_error is True
    assert "JSON" in result.content
    assert stub.calls == []


async def test_execute_non_text_dropped(capsys):
    stub = StubSession().returns(
        call_result([text("keep"), image_block()], is_error=False)
    )
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    result = await tool.execute("{}")
    assert result.content == "keep"
    err = capsys.readouterr().err
    assert "returned non-text content blocks (dropped)" in err


async def test_non_text_warn_once(capsys):
    stub = StubSession().returns(call_result([image_block()], is_error=False))
    tool = adapt_tool("srv", make_tool(name="echo"), stub)
    assert tool is not None
    await tool.execute("{}")
    await tool.execute("{}")
    err = capsys.readouterr().err
    assert err.count("returned non-text content blocks (dropped)") == 1


async def test_non_text_warn_per_tool(capsys):
    stub = StubSession().returns(call_result([image_block()], is_error=False))
    a = adapt_tool("srv", make_tool(name="a"), stub)
    b = adapt_tool("srv", make_tool(name="b"), stub)
    assert a is not None and b is not None
    await a.execute("{}")
    await b.execute("{}")
    err = capsys.readouterr().err
    assert err.count("returned non-text content blocks (dropped)") == 2
