"""mewcode.cli 装配单测（docs/ch07 T5；追加 T13 的 tool_search 闸门）：
无 MCP 配置 / 失败隔离下 _amain 不阻塞、正常返回。"""

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

from mewcode import cli

# 本机 mcp 1.29.0 没有 mcp.server.mcpserver（既有 22 个 mcp 失败同源）：
# 起不了真 stdio server 时跳过，而不是把一个环境问题算成新失败。
_MINI_SERVER_AVAILABLE = importlib.util.find_spec("mcp.server.mcpserver") is not None

MINI_SERVER = """\
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="mini")

@server.tool()
def echo(text: str) -> str:
    return f"echo: {text}"

@server.tool()
def add(a: int, b: int) -> int:
    return a + b

server.run()
"""


def write_config(root: Path) -> None:
    (root / ".mewcode").mkdir(exist_ok=True)
    (root / ".mewcode" / "config.yaml").write_text(
        textwrap.dedent(
            """
            providers:
              - name: a
                protocol: anthropic
                api_key: k
                model: m1
            """
        ).lstrip(),
        encoding="utf-8",
    )


def capture_tools(monkeypatch) -> dict:
    """把 run_async 换成只记录工具名的桩，绕开 TUI。"""
    captured: dict = {}

    async def fake_run_async(self):  # noqa: ARG001 —— 不真正进 TUI
        captured["tools"] = [t.name for t in self.tool_registry.definitions()]
        captured["discovery"] = self.discovery

    monkeypatch.setattr("mewcode.tui.app.MewCodeApp.run_async", fake_run_async)
    return captured


async def test_amain_no_mcp_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    captured = capture_tools(monkeypatch)

    code = await cli._amain()
    assert code == 0
    assert len(captured["tools"]) == 6  # 内置 6 工具
    assert "read_file" in captured["tools"]
    # F16/N10：没有可延迟工具就不注册 tool_search，/status 仍报 6
    assert "tool_search" not in captured["tools"]
    assert captured["discovery"].has_deferrable() is False


async def test_amain_failing_server_does_not_block(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    (tmp_path / ".mewcode.yaml").write_text(
        "mcp_servers:\n  bad: {type: stdio, command: __no_such_cmd__}\n",
        encoding="utf-8",
    )
    captured = capture_tools(monkeypatch)

    code = await cli._amain()
    assert code == 0
    assert not any(name.startswith("mcp__") for name in captured["tools"])  # 失败 server 无工具
    # 连接失败 ⇒ 零可延迟工具 ⇒ 同样不注册 tool_search（闸门看的是工具，不是配置）
    assert "tool_search" not in captured["tools"]
    assert "connect server bad failed" in capsys.readouterr().err


async def test_amain_with_live_server_registers_tool_search(tmp_path, monkeypatch):
    """正方向：真 stdio server 起来后注册 tool_search，且注入的视图看得到它。

    这是 T13 装顺序（MCP 工具 → Discovery → tool_search → App）的端到端证据。
    """
    if not _MINI_SERVER_AVAILABLE:
        pytest.skip("本机 mcp 版本无 mcp.server.mcpserver，起不了真 stdio server")
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    script = tmp_path / "mini_server.py"
    script.write_text(MINI_SERVER, encoding="utf-8")
    exe = sys.executable.replace("\\", "/")  # 正斜杠 + 单引号：免掉 YAML 转义与空格问题
    (tmp_path / ".mewcode.yaml").write_text(
        "mcp_servers:\n"
        f"  ok:\n    type: stdio\n    command: '{exe}'\n    args: ['{script.name}']\n",
        encoding="utf-8",
    )
    captured = capture_tools(monkeypatch)

    code = await cli._amain()
    assert code == 0
    tools = captured["tools"]
    assert "tool_search" in tools
    assert sorted(n for n in tools if n.startswith("mcp__")) == [
        "mcp__ok__add",
        "mcp__ok__echo",
    ]
    # 视图与 tool_search 持有同一份：注册中心里可延迟的正是那两个 MCP 工具
    assert captured["discovery"].has_deferrable() is True
    assert sorted(captured["discovery"].deferred_names()) == [
        "mcp__ok__add",
        "mcp__ok__echo",
    ]
