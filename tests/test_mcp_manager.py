"""mcp/manager 模块单测（docs/ch07 T4）：并发连接 / 失败隔离 / 超时 / 关闭兜底 / 排序。"""

import asyncio
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from mcp import types as mtypes

from mewcode.mcp import new_manager
from mewcode.mcp import manager as manager_mod
from mewcode.mcp.config import Config, ServerConfig
from mewcode.mcp.tool import McpTool

MINI_SERVER = """\
from mcp.server.fastmcp import FastMCP

server = FastMCP("mini")

@server.tool()
def echo(text: str) -> str:
    return f"echo: {text}"

@server.tool()
def add(a: int, b: int) -> int:
    return a + b

server.run(transport="stdio")
"""


class DummySession:
    """最小 CallerSession 替身（仅用于注册工具，不实际调用）。"""

    async def call_tool(self, name: str, arguments: Any) -> mtypes.CallToolResult:
        return mtypes.CallToolResult.model_validate({"content": [], "isError": False})


def fake_tool(server: str, name: str = "tool") -> McpTool:
    return McpTool(
        full_name=f"mcp__{server}__{name}",
        remote_name=name,
        _description="d",
        _parameters={"type": "object"},
        read_only=False,
        caller=DummySession(),
    )


async def test_empty_config():
    cfg = Config()
    mgr = await new_manager(cfg, "0.1.0")
    assert mgr.tools() == []
    await mgr.close()


async def test_failure_isolation(tmp_path, capsys):
    """一个失败 server 只跳过自身；成功 server 的工具照常注册。"""
    script = tmp_path / "mini_server.py"
    script.write_text(MINI_SERVER, encoding="utf-8")
    cfg = Config(
        servers={
            "bad": ServerConfig(type="stdio", command="__no_such_command_xyz__", args=[]),
            "ok": ServerConfig(type="stdio", command=sys.executable, args=[str(script)]),
        }
    )
    mgr = await new_manager(cfg, "0.1.0")
    assert sorted(t.name() for t in mgr.tools()) == ["mcp__ok__add", "mcp__ok__echo"]
    assert "connect server bad failed" in capsys.readouterr().err
    await mgr.close()


@asynccontextmanager
async def hanging_stdio(params):
    """aenter 永不返回的假 stdio 传输，用于连接超时测试。"""
    await asyncio.Event().wait()
    yield


async def test_connect_timeout(monkeypatch, capsys):
    from mcp.client import stdio as stdio_mod

    monkeypatch.setattr(stdio_mod, "stdio_client", hanging_stdio)
    monkeypatch.setattr(manager_mod, "connect_timeout", 0.2)
    cfg = Config(servers={"hang": ServerConfig(type="stdio", command="x", args=[])})
    t0 = time.monotonic()
    mgr = await new_manager(cfg, "0.1.0")
    elapsed = time.monotonic() - t0
    assert mgr.tools() == []
    assert elapsed < 5  # 受缩短的 connect_timeout 约束，不阻塞启动
    assert "timeout" in capsys.readouterr().err
    await mgr.close()


class BlockingExit:
    """__aexit__ 永不返回的假上下文，用于关闭兜底测试。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any) -> None:
        await asyncio.Event().wait()


async def test_close_timeout(monkeypatch, capsys):
    async def stub_do_connect(mgr, name, srv, version, done):  # noqa: ARG001
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            await stack.enter_async_context(BlockingExit())
            async with mgr._lock:
                mgr._tools.append(fake_tool(name))
            done.set()
            await mgr._shutdown.wait()
        finally:
            await stack.aclose()  # 阻塞在 BlockingExit.__aexit__

    monkeypatch.setattr(manager_mod, "_do_connect", stub_do_connect)
    monkeypatch.setattr(manager_mod, "close_timeout", 0.2)
    cfg = Config(servers={"stuck": ServerConfig(type="stdio", command="x", args=[])})
    mgr = await new_manager(cfg, "0.1.0")
    assert len(mgr.tools()) == 1
    t0 = time.monotonic()
    await mgr.close()
    elapsed = time.monotonic() - t0
    assert elapsed < 5  # 5s 兜底内返回，不阻塞退出
    assert "close timeout" in capsys.readouterr().err


async def test_tools_sorted_by_full_name(monkeypatch):
    """并发连接完成后按 full_name 排序，与完成先后无关。"""

    async def stub_do_connect(mgr, name, srv, version, done):  # noqa: ARG001
        delay = {"z": 0.0, "a": 0.2}[name]
        await asyncio.sleep(delay)
        async with mgr._lock:
            mgr._tools.append(fake_tool(name))
        done.set()
        await mgr._shutdown.wait()

    monkeypatch.setattr(manager_mod, "_do_connect", stub_do_connect)
    cfg = Config(
        servers={
            "z": ServerConfig(type="stdio", command="x", args=[]),
            "a": ServerConfig(type="stdio", command="x", args=[]),
        }
    )
    mgr = await new_manager(cfg, "0.1.0")
    # z 先登记（delay 0）而 a 后登记（delay 0.2）；排序后 a 在前
    assert [t.name() for t in mgr.tools()] == ["mcp__a__tool", "mcp__z__tool"]
    await mgr.close()


async def test_real_stdio_integration(tmp_path):
    """真实拉起一个 stdio MCP server 子进程：连接 → 握手 → 列工具 → 调用 → 干净关闭。"""
    script = tmp_path / "mini_server.py"
    script.write_text(MINI_SERVER, encoding="utf-8")
    cfg = Config(
        servers={"mini": ServerConfig(type="stdio", command=sys.executable, args=[str(script)])}
    )
    mgr = await new_manager(cfg, "0.1.0")
    tools = {t.name(): t for t in mgr.tools()}
    assert set(tools) == {"mcp__mini__add", "mcp__mini__echo"}

    r = await tools["mcp__mini__add"].execute('{"a": 2, "b": 3}')
    assert r.content == "5" and r.is_error is False
    r = await tools["mcp__mini__echo"].execute('{"text": "hi"}')
    assert r.content == "echo: hi" and r.is_error is False
    await mgr.close()
