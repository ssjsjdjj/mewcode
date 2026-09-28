"""Registry 的 Skill 相关扩展测试（docs/ch11 T14）：白名单过滤 / 系统工具 / 专属工具注册。"""

from __future__ import annotations

from typing import Any

from mewcode.tool import Result, Tool, new_default_registry


class StubTool:
    """可配置的最小 Tool 实现。"""

    def __init__(self, name: str, *, read_only: bool = False, is_system: bool = False) -> None:
        self._name = name
        self._read_only = read_only
        self._is_system = is_system

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"{self._name} 的描述"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def deferrable(self) -> bool:
        return False

    @property
    def is_system(self) -> bool:
        return self._is_system

    async def execute(self, args: str) -> Result:
        return Result(content=f"{self._name} 跑过了")


def test_is_system_defaults_false_for_builtins():
    """既有 6 个内置工具都没声明 is_system，读端一律按 False（不破坏既有实现）。"""
    reg = new_default_registry()
    for name in ("read_file", "write_file", "bash", "glob", "grep", "edit_file"):
        assert reg.is_system(name) is False
    assert reg.system_definitions() == []


def test_is_system_unknown_tool():
    assert new_default_registry().is_system("nope") is False


def test_definitions_filtered_narrows():
    reg = new_default_registry()
    reg.register(StubTool("sys", is_system=True))
    names = [d.name for d in reg.definitions_filtered(["read_file", "grep"])]
    assert names == ["read_file", "grep", "sys"]  # 系统工具豁免


def test_definitions_filtered_empty_means_no_narrowing():
    """空白名单 = 不再收窄，系统工具自然仍在（checklist：definitions_filtered([]) 含 load_skill）。"""
    reg = new_default_registry()
    reg.register(StubTool("load_skill", read_only=True, is_system=True))
    names = [d.name for d in reg.definitions_filtered([])]
    assert names == [d.name for d in reg.definitions()]
    assert "load_skill" in names


def test_definitions_filtered_preserves_registration_order():
    reg = new_default_registry()
    names = [d.name for d in reg.definitions_filtered(["grep", "read_file"])]
    assert names == ["read_file", "grep"]  # 按注册顺序，不按白名单顺序


def test_register_skill_tool_overwrites_silently():
    """专属工具重名静默覆盖——与 register 的硬失败语义相反（F23）。"""
    reg = new_default_registry()
    reg.register_skill_tool(StubTool("echo"))
    assert reg.get("echo") is not None
    assert reg.count() == 7

    reg.register_skill_tool(StubTool("echo"))  # 再来一次不抛异常
    assert reg.count() == 7  # 不重复占位
    assert reg.get("echo") is not None


def test_register_skill_tool_cannot_shadow_silently_breaking_order():
    """覆盖既有内置工具名：条目位置不变。"""
    reg = new_default_registry()
    before = [d.name for d in reg.definitions()]
    reg.register_skill_tool(StubTool("bash"))
    assert [d.name for d in reg.definitions()] == before
    assert reg.count() == 6


def test_stub_conforms_to_tool_protocol():
    assert isinstance(StubTool("x"), Tool)
