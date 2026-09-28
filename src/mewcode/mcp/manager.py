"""MCP 连接管理器：并发连接全部 server、缓存会话、统一关闭（docs/ch07 T4）。

启动时对每个配置的 server 做「连接 → 握手 → 列工具」三步，任一 server 失败 / 超时
只跳过它自身（N1）；所有连接尝试结束后才返回，进 TUI 时工具集稳定。

每个连接是一个长驻 worker task，在本 task 内用局部 AsyncExitStack 进入 transport 与
ClientSession 上下文、握手、列工具、登记，然后阻塞在 shutdown event 上；close() 触发
shutdown → 各 worker 在自己的 task 内退出上下文（stdio 子进程终止 / HTTP 断开），
整体 5s 兜底（N7）。上下文必须由同一 task 进入并退出——mcp 2.0 的 anyio 传输把
cancel scope 绑定在进入它的 task 上，跨 task 退出会抛 RuntimeError，因此不用共享栈。
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass

from mcp import ClientSession
import mcp.types as mtypes

from .config import Config, ServerConfig
from .tool import McpTool, adapt_tool

# 模块级超时（非常量，单测可临时改小；生产 30s / 5s，F9/F11）
connect_timeout: float = 30.0
close_timeout: float = 5.0


def _warn(msg: str) -> None:
    print(f"[mcp] warn: {msg}", file=sys.stderr)


@dataclass
class _Session:
    name: str
    session: ClientSession


class Manager:
    """持有全部已建立会话与适配好的工具；close() 触发统一清理。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._shutdown = asyncio.Event()  # close() 置位，唤醒长驻连接 worker
        self._conn_done: list[asyncio.Event] = []  # 每 server 一个：连接阶段结束信号
        self._conn_tasks: list[asyncio.Task] = []  # 每 server 一个长驻 worker task

    def tools(self) -> list[McpTool]:
        """已适配工具列表副本（按 full_name 稳定排序，防外部修改）。"""
        return list(self._tools)

    async def close(self) -> None:
        """关闭全部会话（stdio 子进程终止 / HTTP 断开）；5s 兜底绝不阻塞退出。"""
        self._shutdown.set()
        if not self._conn_tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._conn_tasks, return_exceptions=True),
                timeout=close_timeout,
            )
        except asyncio.TimeoutError:
            for task in self._conn_tasks:
                task.cancel()
            await asyncio.gather(*self._conn_tasks, return_exceptions=True)
            _warn(f"close timeout ({close_timeout}s), some sessions may leak")


async def new_manager(cfg: Config, version: str) -> Manager:
    """并发连接所有 server；每个 server 受 connect_timeout 约束，失败仅跳过自身。"""
    mgr = Manager()
    for name, srv in cfg.servers.items():
        done = asyncio.Event()
        mgr._conn_done.append(done)
        mgr._conn_tasks.append(asyncio.create_task(_connect_one(mgr, name, srv, version, done)))
    # 等所有 server 的连接阶段结束（成功 / 失败 / 超时），再返回进 TUI（F9）
    await asyncio.gather(*[d.wait() for d in mgr._conn_done])
    mgr._tools.sort(key=lambda t: t.full_name)
    return mgr


async def _connect_one(
    mgr: Manager, name: str, srv: ServerConfig, version: str, done: asyncio.Event
) -> None:
    """单个 server 的连接 worker：超时 / 异常均吸收为 stderr 告警，不向上抛。

    失败 / 超时路径在此收尾并置位 done（成功路径由 _do_connect 内部置位，此处幂等兜底）。
    """
    try:
        await _do_connect(mgr, name, srv, version, done)
    except asyncio.TimeoutError:
        _warn(f"connect server {name} timeout after {connect_timeout}s")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 单 server 失败隔离（N1）
        _warn(f"connect server {name} failed: {exc}")
    finally:
        done.set()


async def _do_connect(
    mgr: Manager, name: str, srv: ServerConfig, version: str, done: asyncio.Event
) -> None:
    """建立 transport 与 ClientSession、握手、列工具、适配登记，随后阻塞到 shutdown。

    transport / session 上下文全部由本 task 进入并退出（局部 AsyncExitStack），
    连接三步（进入上下文 + 握手 + 列工具）整体受 connect_timeout 约束。
    """
    if srv.type == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=srv.command,
            args=srv.args,
            env={**os.environ, **srv.env},  # 同名宿主变量被 srv.env 覆盖（F4）
        )
        ctx = stdio_client(params)
    else:
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        ctx = streamable_http_client(
            srv.url,
            http_client=httpx2.AsyncClient(headers=srv.headers or None),  # 鉴权头注入（F5）
        )

    stack = AsyncExitStack()
    try:
        async with asyncio.timeout(connect_timeout):
            streams = await stack.enter_async_context(ctx)
            # stdio 产出 2 元组 (read, write)；http 传输在 mcp 新版多返回一个
            # get_session_id 变 3 元组。两种形状都只取前两个流（TransportStreams）。
            read, write = streams[0], streams[1]
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    client_info=mtypes.Implementation(name="mewcode", version=version),
                )
            )
            await session.initialize()  # 握手
            listed = await session.list_tools()

        dedup: dict[str, McpTool] = {}
        for t in listed.tools:
            tool = adapt_tool(name, t, session)
            if tool is None:
                continue
            if tool.full_name in dedup:
                _warn(f"duplicate tool {tool.full_name} from server {name}, keeping the later")
            dedup[tool.full_name] = tool  # 后注册者保留（F8）
        adapted = list(dedup.values())

        async with mgr._lock:
            mgr._sessions.append(_Session(name, session))
            mgr._tools.extend(adapted)

        done.set()  # 连接阶段结束（成功），new_manager 可返回进 TUI

        # 连接阶段完成：保持上下文存活（子进程 / HTTP 会话），直到 close() 触发
        await mgr._shutdown.wait()
    finally:
        await stack.aclose()  # 本 task 内退出全部上下文（N7）
