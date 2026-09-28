"""命令行入口（docs/ch02 T13；ch03 T17 注入工具注册中心；ch06 注入权限引擎；ch07 装配 MCP 客户端）。

ch09 T16：启动流程串联三层记忆——加载 MEWCODE.md 指令、初始化记忆管理器、
创建会话 Writer、异步清理过期会话，并注入 MewCodeApp 与 Agent。

ch07 追加 T13：MCP 工具注册后建一份延迟加载视图，并在存在可延迟工具时注册 tool_search。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from mewcode import __version__, instructions, memory, mcp as mcp_client
from mewcode import config as config_mod
from mewcode import session as session_mod
from mewcode.agent import SessionRuntime
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.config import ConfigError, effective_context_window
from mewcode.permission import new_engine
from mewcode.tool import new_default_registry
from mewcode.tool.deferred import Discovery
from mewcode.tool.tool_search import ToolSearchTool
from mewcode.tui.app import MewCodeApp

CONFIG_PATH = ".mewcode/config.yaml"


async def _amain() -> int:
    try:
        cfg = config_mod.load(CONFIG_PATH)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    root = str(Path.cwd().resolve())
    # 第 1 层记忆：三层 MEWCODE.md 指令（docs/ch09 T16）；记忆管理器在 provider
    # 选定前为惰性（update_async 直接返回），load_index 只读两级索引
    instruction_text = instructions.Loader(root).load()
    mem_mgr = memory.Manager(
        str(Path(root) / ".mewcode" / "memory"),
        str(Path.home() / ".mewcode" / "memory"),
        provider=None,
        model="",
    )
    memory_text = mem_mgr.load_index()

    registry = new_default_registry()
    mcp_mgr = await mcp_client.new_manager(mcp_client.load_config(root), version=__version__)
    try:
        for tool in mcp_mgr.tools():
            registry.register(tool)
        # 延迟加载视图（docs/ch07 追加 T13）：MCP 工具注册完才建，因此它一眼就能看到
        # 全部可延迟工具；无 MCP 工具时不注册 tool_search——没有可拉取的东西，多一个
        # 工具只会多烧 token 与一次调用机会（F16）。
        discovery = Discovery(registry)
        if discovery.has_deferrable():
            registry.register(ToolSearchTool(discovery))
        engine, err = new_engine(root)
        if err is not None:
            print(f"权限引擎降级: {err}", file=sys.stderr)
        # 过期会话清理：删除 30 天前的会话目录（docs/ch09 F25），后台线程执行不阻塞启动
        asyncio.create_task(
            asyncio.to_thread(
                session_mod.clean_expired,
                str(Path(root) / ".mewcode" / "sessions"),
                timedelta(days=30),
            )
        )
        # 每会话一份 SessionRuntime（docs/ch08 T32）：单 provider 启动期即可定
        # context_window；多 provider 待 TUI 选中后再回调注入
        ses_ctx = new_session_context(workspace=str(Path.cwd()))
        writer = session_mod.Writer(ses_ctx.session_dir)  # 第 2 层：JSONL 会话存档
        replacement = ContentReplacementState()
        recovery = RecoveryState()
        auto_tracking = CompactCircuitBreaker()
        if len(cfg.providers) == 1:
            runtime = SessionRuntime(
                replacement,
                recovery,
                auto_tracking,
                ses_ctx,
                context_window=effective_context_window(cfg.providers[0]),
            )
        else:
            runtime = SessionRuntime(replacement, recovery, auto_tracking, ses_ctx)
        app = MewCodeApp(
            cfg.providers,
            __version__,
            registry,
            engine=engine,
            runtime=runtime,
            writer=writer,
            mem_mgr=mem_mgr,
            instruction_text=instruction_text,
            memory_text=memory_text,
            discovery=discovery,
        )
        try:
            await app.run_async()
        except KeyboardInterrupt:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"程序异常: {exc}", file=sys.stderr)
            return 1
    finally:
        await mcp_mgr.close()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))
