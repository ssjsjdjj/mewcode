"""ToolSearch 工具单测（docs/ch07 追加 T12；F16–F18 / AC17–AC19）。"""

from __future__ import annotations

import json

from mewcode.tool import Registry, Result
from mewcode.tool.deferred import Discovery
from mewcode.tool.tool_search import SELECT_PREFIX, ToolSearchTool


class _StubDiscovery:
    """只记录调用并返回预置结果，用于断言路由。"""

    def __init__(self, result: Result | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.result = result or Result(content="ok")

    def select(self, name: str) -> Result:
        self.calls.append(("select", name))
        return self.result

    def search(self, keyword: str) -> Result:
        self.calls.append(("search", keyword))
        return self.result


class _FakeTool:
    def __init__(self, name: str, *, desc: str = "", deferrable: bool = True) -> None:
        self._name = name
        self._desc = desc or f"{name} 的描述"
        self._deferrable = deferrable

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._desc

    def parameters(self) -> dict:
        return {"type": "object", "properties": {"q": {"type": "string"}}}

    @property
    def read_only(self) -> bool:
        return True

    @property
    def deferrable(self) -> bool:
        return self._deferrable

    async def execute(self, args: str):  # pragma: no cover
        raise AssertionError("tool_search 假件不应被执行")


def _kw(text: str) -> str:
    return json.dumps({"keyword": text}, ensure_ascii=False)


def _discovery_with(*tools: _FakeTool) -> Discovery:
    r = Registry()
    for t in tools:
        r.register(t)
    return Discovery(r)


# ---------- F16：作为普通内置工具存在 ----------


def test_identity_and_flags():
    tool = ToolSearchTool(_StubDiscovery())
    assert tool.name() == "tool_search"
    assert tool.read_only is True  # Plan Mode 下可见
    assert tool.deferrable is False  # 自身不可延迟，否则永远拉不到


def test_parameters_require_keyword():
    params = ToolSearchTool(_StubDiscovery()).parameters()
    assert params["type"] == "object"
    assert params["required"] == ["keyword"]
    assert params["properties"]["keyword"]["type"] == "string"


# ---------- F17/F18：单入口路由 ----------


async def test_select_prefix_routes_to_select():
    stub = _StubDiscovery()
    tool = ToolSearchTool(stub)
    out = await tool.execute(_kw(f"{SELECT_PREFIX}mcp__fs__read"))
    assert stub.calls == [("select", "mcp__fs__read")]
    assert out.is_error is False


async def test_select_prefix_strips_only_prefix_and_strips_spaces():
    stub = _StubDiscovery()
    await ToolSearchTool(stub).execute(_kw(f"  {SELECT_PREFIX}  mcp__fs__read  "))
    assert stub.calls == [("select", "mcp__fs__read")]


async def test_plain_keyword_routes_to_search():
    stub = _StubDiscovery()
    await ToolSearchTool(stub).execute(_kw("github"))
    await ToolSearchTool(stub).execute(_kw("  github  "))
    assert stub.calls == [("search", "github"), ("search", "github")]


async def test_downstream_result_passed_through_unchanged():
    miss = Result(content="没有名为 x 的工具。", is_error=True)
    tool = ToolSearchTool(_StubDiscovery(miss))
    out = await tool.execute(_kw(f"{SELECT_PREFIX}x"))
    assert out is miss  # 不重新包装、不改写错误文本


# ---------- AC19：参数问题一律是错误结果，不是异常 ----------


async def test_invalid_json_is_error():
    out = await ToolSearchTool(_StubDiscovery()).execute("{不是 json")
    assert out.is_error is True
    assert "JSON" in out.content


async def test_non_object_json_is_error():
    out = await ToolSearchTool(_StubDiscovery()).execute("[1, 2]")
    assert out.is_error is True
    assert "对象" in out.content


async def test_missing_or_blank_keyword_is_error():
    tool = ToolSearchTool(_StubDiscovery())
    for args in ("", "{}", _kw("   "), json.dumps({"keyword": 123})):
        out = await tool.execute(args)
        assert out.is_error is True
        assert "keyword" in out.content


async def test_parameter_error_does_not_touch_discovery():
    stub = _StubDiscovery()
    for args in ("", "{}", "{不是 json"):
        await ToolSearchTool(stub).execute(args)
    assert stub.calls == []


# ---------- 与真实 Discovery 的集成 ----------


async def test_integration_fetch_then_visible():
    d = _discovery_with(
        _FakeTool("mcp__fs__read", desc="读文件", deferrable=True),
        _FakeTool("mcp__fs__write", desc="写文件", deferrable=True),
    )
    tool = ToolSearchTool(d)
    assert [x.name for x in d.visible_definitions(plan_only=False)] == []
    out = await tool.execute(_kw(f"{SELECT_PREFIX}mcp__fs__read"))
    assert out.is_error is False
    assert "读文件" in out.content
    assert "input_schema" in out.content or "schema" in out.content
    assert [x.name for x in d.visible_definitions(plan_only=False)] == ["mcp__fs__read"]


async def test_integration_select_miss_is_error():
    tool = ToolSearchTool(_discovery_with(_FakeTool("mcp__fs__read")))
    out = await tool.execute(_kw(f"{SELECT_PREFIX}mcp__fs__nope"))
    assert out.is_error is True
    assert "mcp__fs__nope" in out.content


async def test_integration_search_then_visible():
    d = _discovery_with(
        _FakeTool("mcp__s__sql_query", desc="跑 SQL"),
        _FakeTool("mcp__s__noise", desc="无关"),
    )
    tool = ToolSearchTool(d)
    out = await tool.execute(_kw("sql"))
    assert out.is_error is False
    assert "mcp__s__sql_query" in d.discovered_names()
    assert [x.name for x in d.visible_definitions(plan_only=False)] == ["mcp__s__sql_query"]


async def test_integration_search_zero_hits_is_error():
    tool = ToolSearchTool(_discovery_with(_FakeTool("mcp__s__noise")))
    out = await tool.execute(_kw("绝不可能命中的词"))
    assert out.is_error is True
