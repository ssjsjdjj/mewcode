"""Skill 专属工具（tool.json 适配）测试（docs/ch11 T15/N12）。

用 `sys.executable -c` 起脚本而不是 .sh——Windows 上不可执行 shell 脚本，
测试须跨平台。
"""

from __future__ import annotations

import sys

from mewcode.tool import skill_tool as skill_tool_mod
from mewcode.tool.skill_tool import new_skill_tool


def make(pycode: str, tmp_path, name: str = "demo"):
    return new_skill_tool(
        name=name,
        description="示范工具",
        input_schema={"type": "object", "properties": {}},
        command=[sys.executable, "-c", pycode],
        base_dir=tmp_path,
    )


async def test_success_output_becomes_result(tmp_path):
    tool = make("print('ok')", tmp_path)
    r = await tool.execute("{}")
    assert r.is_error is False
    assert r.content.strip() == "ok"


async def test_stdin_receives_json_args(tmp_path):
    tool = make("import sys; sys.stdout.write(sys.stdin.read())", tmp_path)
    r = await tool.execute('{"a": 1}')
    assert r.is_error is False
    assert r.content.strip() == '{"a": 1}'


async def test_empty_args_sends_empty_object(tmp_path):
    tool = make("import sys; sys.stdout.write(sys.stdin.read())", tmp_path)
    r = await tool.execute("")
    assert r.is_error is False
    assert r.content.strip() == "{}"


async def test_nonzero_exit_is_failure(tmp_path):
    """returncode != 0 视为失败，stderr 并入结果（N12）。"""
    tool = make("import sys; sys.stderr.write('boom'); sys.exit(3)", tmp_path)
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "exit 3" in r.content
    assert "boom" in r.content


async def test_cwd_is_base_dir(tmp_path):
    tool = make("import os; print(os.getcwd())", tmp_path)
    r = await tool.execute("{}")
    assert r.is_error is False
    assert str(tmp_path) in r.content


async def test_timeout(tmp_path, monkeypatch):
    """超出固定超时 → 错误结果，进程被杀（N12 的 30s 上限）。"""
    monkeypatch.setattr(skill_tool_mod, "SKILL_TOOL_TIMEOUT", 0.3)
    tool = make("import time; time.sleep(10)", tmp_path)
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "超时" in r.content


async def test_missing_command_is_error(tmp_path):
    tool = new_skill_tool(
        name="bad",
        description="d",
        input_schema={},
        command=["__no_such_binary_xyz__"],
        base_dir=tmp_path,
    )
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "无法启动" in r.content


async def test_read_only_and_is_system_flags(tmp_path):
    tool = make("print(1)", tmp_path)
    assert tool.read_only is False
    assert tool.deferrable is False
    assert tool.is_system is False
