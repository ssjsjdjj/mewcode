"""延迟加载视图单测（docs/ch07 追加 T11；F13–F20 / AC16–AC20）。"""

from __future__ import annotations

import json

from mewcode.tool import Registry
from mewcode.tool.deferred import SEARCH_LIMIT, Discovery

BUILTIN_NAMES = ["read_file", "write_file", "edit_file", "bash", "glob", "grep"]
READ_ONLY_BUILTINS = {"read_file", "glob", "grep"}


class _FakeTool:
    """最小 Tool 假件；`deferrable` 由构造参数决定（不依赖名字前缀）。"""

    def __init__(
        self,
        name: str,
        *,
        desc: str = "",
        read_only: bool = True,
        deferrable: bool = False,
    ) -> None:
        self._name = name
        self._desc = desc or f"{name} 的描述"
        self._read_only = read_only
        self._deferrable = deferrable

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._desc

    def parameters(self) -> dict:
        return {"type": "object", "properties": {"q": {"type": "string"}}}

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def deferrable(self) -> bool:
        return self._deferrable

    async def execute(self, args: str):  # pragma: no cover —— 本模块不执行工具
        raise AssertionError("延迟加载视图不应执行工具")


def _registry(*tools: _FakeTool) -> Registry:
    r = Registry()
    for t in tools:
        r.register(t)
    return r


def _builtin_registry() -> Registry:
    return _registry(*[_FakeTool(n, read_only=n in READ_ONLY_BUILTINS) for n in BUILTIN_NAMES])


def _mcp_tool(server: str, tool: str, **kw) -> _FakeTool:
    return _FakeTool(f"mcp__{server}__{tool}", desc=f"{server} 的 {tool}", deferrable=True, **kw)


def _snapshot(defs) -> list[tuple[str, str, str]]:
    return [
        (d.name, d.description, json.dumps(d.input_schema, sort_keys=True, ensure_ascii=False))
        for d in defs
    ]


# ---------- F23：无可延迟工具时是恒等变换 ----------


def test_no_deferrable_is_identity():
    r = _builtin_registry()
    d = Discovery(r)
    assert d.has_deferrable() is False
    assert d.deferred_names() == []
    assert d.manifest() is None
    assert _snapshot(d.visible_definitions(plan_only=False)) == _snapshot(r.definitions())
    assert _snapshot(d.visible_definitions(plan_only=True)) == _snapshot(r.read_only_definitions())


# ---------- F13/F14：声明决定延迟，与名字前缀无关 ----------


def test_deferrable_without_mcp_prefix_is_also_deferred():
    """F13 核心：可延迟由工具自身声明，注册中心不按 `mcp__` 前缀推断。"""
    r = _builtin_registry()
    r.register(_FakeTool("vendor_search", deferrable=True))
    d = Discovery(r)
    assert d.has_deferrable() is True
    assert d.deferred_names() == ["vendor_search"]
    assert "vendor_search" not in [x.name for x in d.visible_definitions(plan_only=False)]
    assert "[其他]" in d.manifest()


def test_deferred_hidden_until_selected():
    r = _builtin_registry()
    r.register(_mcp_tool("fs", "read"))
    d = Discovery(r)
    assert "mcp__fs__read" not in [x.name for x in d.visible_definitions(plan_only=False)]
    out = d.select("mcp__fs__read")
    assert out.is_error is False
    assert "mcp__fs__read" in out.content
    assert "mcp__fs__read" in [x.name for x in d.visible_definitions(plan_only=False)]


def test_visible_order_is_registration_order():
    r = _registry(
        *[
            _FakeTool("read_file", read_only=True),
            _mcp_tool("a", "one"),
            _FakeTool("bash", read_only=False),
            _mcp_tool("a", "two"),
            _FakeTool("grep", read_only=True),
        ]
    )
    d = Discovery(r)
    d.select("mcp__a__two")
    assert [x.name for x in d.visible_definitions(plan_only=False)] == [
        "read_file",
        "bash",
        "mcp__a__two",
        "grep",
    ]


# ---------- F22：Plan Mode 叠加在只读子集之上 ----------


def test_plan_only_filters_then_defers():
    r = _builtin_registry()
    r.register(_mcp_tool("fs", "read", read_only=True))
    r.register(_mcp_tool("fs", "write", read_only=False))
    d = Discovery(r)
    d.select("mcp__fs__read")
    d.select("mcp__fs__write")
    plan_names = [x.name for x in d.visible_definitions(plan_only=True)]
    assert "mcp__fs__read" in plan_names  # 只读且已拉取 → 可见
    assert "mcp__fs__write" not in plan_names  # 写类 → 即便拉取过也不可见
    assert "write_file" not in plan_names
    assert "read_file" in plan_names


# ---------- F15：清单 ----------


def test_manifest_groups_and_sorts_deterministically():
    r = _builtin_registry()
    for name in ("mcp__b__two", "mcp__a__zebra", "mcp__b__one", "mcp__a__ant"):
        r.register(_FakeTool(name, desc=f"{name} 的说明", deferrable=True))
    d = Discovery(r)
    text = d.manifest()
    assert text is not None
    body = text.splitlines()
    assert "[a]" in body and "[b]" in body
    assert body.index("[a]") < body.index("[b]")  # 组间按 server 名排序
    a_items = [line for line in body if line.startswith("- mcp__a__")]
    assert a_items == ["- mcp__a__ant", "- mcp__a__zebra"]  # 组内按全名排序
    assert "的说明" not in text  # 清单只含名字，不含描述与 schema


def test_manifest_has_no_count_cap():
    r = _builtin_registry()
    for i in range(30):
        r.register(_FakeTool(f"mcp__s__t{i:02d}", deferrable=True))
    text = Discovery(r).manifest()
    assert text is not None
    assert sum(1 for line in text.splitlines() if line.startswith("- mcp__")) == 30


def test_manifest_none_when_all_discovered():
    r = _builtin_registry()
    r.register(_mcp_tool("fs", "read"))
    d = Discovery(r)
    assert d.manifest() is not None
    d.select("mcp__fs__read")
    assert d.manifest() is None
    r.register(_mcp_tool("fs", "write"))
    assert d.manifest() is not None  # 新出现的延迟工具重新进入清单


# ---------- F17：精确拉取 ----------


def test_select_miss_is_error_not_exception():
    d = Discovery(_builtin_registry())
    out = d.select("mcp__nope__nope")
    assert out.is_error is True
    assert "mcp__nope__nope" in out.content


def test_select_empty_name_is_error():
    d = Discovery(_builtin_registry())
    assert d.select("   ").is_error is True


def test_select_is_idempotent():
    r = _builtin_registry()
    r.register(_mcp_tool("fs", "read"))
    d = Discovery(r)
    first = d.select("mcp__fs__read")
    second = d.select("mcp__fs__read")
    assert first.is_error is second.is_error is False
    assert d.discovered_names() == ["mcp__fs__read"]
    assert d.manifest() is None


def test_select_non_deferrable_returns_definition_without_polluting_found():
    d = Discovery(_builtin_registry())
    out = d.select("read_file")
    assert out.is_error is False
    assert "read_file" in out.content
    assert d.discovered_names() == []


# ---------- F18：关键词搜索 ----------


def test_search_name_hits_rank_above_description_hits():
    r = _builtin_registry()
    r.register(_FakeTool("mcp__s__alpha", desc="无关说明", deferrable=True))
    r.register(_FakeTool("mcp__s__beta", desc="描述里提到 alpha 的工具", deferrable=True))
    out = Discovery(r).search("alpha")
    assert out.is_error is False
    lines = [line for line in out.content.splitlines() if line.startswith("- ")]
    assert lines[0].startswith("- mcp__s__alpha")
    assert lines[1].startswith("- mcp__s__beta")


def test_search_limit_and_truncation_note():
    r = _builtin_registry()
    for i in range(SEARCH_LIMIT + 3):
        r.register(_FakeTool(f"mcp__s__sql{i}", deferrable=True))
    d = Discovery(r)
    out = d.search("sql")
    shown = [line for line in out.content.splitlines() if line.startswith("- ")]
    assert len(shown) == SEARCH_LIMIT
    assert f"共 {SEARCH_LIMIT + 3} 个匹配" in out.content
    assert len(d.discovered_names()) == SEARCH_LIMIT  # 只标记实际返回的那些
    assert len(d.deferred_names()) == 3


def test_search_marks_all_shown_and_is_idempotent():
    r = _builtin_registry()
    r.register(_FakeTool("mcp__s__sql", deferrable=True))
    d = Discovery(r)
    first = d.search("sql")
    second = d.search("sql")
    assert first.content == second.content  # 幂等：结果文本不因已发现而变
    assert d.discovered_names() == ["mcp__s__sql"]


def test_search_zero_hits_is_error():
    d = Discovery(_builtin_registry())
    out = d.search("绝不可能命中的词")
    assert out.is_error is True
    assert d.discovered_names() == []


def test_search_empty_keyword_is_error():
    d = Discovery(_builtin_registry())
    assert d.search("  ").is_error is True


# ---------- F19：会话内存态 ----------


def test_reset_restores_initial_view():
    r = _builtin_registry()
    r.register(_mcp_tool("fs", "read"))
    d = Discovery(r)
    before = _snapshot(d.visible_definitions(plan_only=False))
    d.select("mcp__fs__read")
    assert d.discovered_names() == ["mcp__fs__read"]
    d.reset()
    assert d.discovered_names() == []
    assert _snapshot(d.visible_definitions(plan_only=False)) == before
    assert d.manifest() is not None


def test_reset_is_idempotent():
    d = Discovery(_builtin_registry())
    d.reset()
    d.reset()
    assert d.discovered_names() == []


# ---------- N11：确定性 ----------


def test_determinism_across_instances():
    def build() -> Discovery:
        r = _builtin_registry()
        for name in ("mcp__b__two", "mcp__a__one", "mcp__a__two"):
            r.register(_FakeTool(name, desc=f"{name} d", deferrable=True))
        return Discovery(r)

    d1, d2 = build(), build()
    assert d1.manifest() == d2.manifest()
    d1.search("two")
    d2.search("two")
    assert _snapshot(d1.visible_definitions(plan_only=False)) == _snapshot(
        d2.visible_definitions(plan_only=False)
    )
    assert d1.manifest() == d2.manifest()
