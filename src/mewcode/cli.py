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
from mewcode import hook
from mewcode import session as session_mod
from mewcode.agent import SessionRuntime
from mewcode.command import SkillSummary, register_skills_as_commands
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.config import ConfigError, effective_context_window
from mewcode.hook import Event
from mewcode.llm import new_provider
from mewcode.permission import new_engine
from mewcode.skills import Catalog, Executor
from mewcode.tool import new_default_registry
from mewcode.tool.deferred import Discovery
from mewcode.tool.install_skill import InstallSkillTool
from mewcode.tool.load_skill import LoadSkillTool
from mewcode.tool.tool_search import ToolSearchTool
from mewcode.tui.app import MewCodeApp

CONFIG_PATH = ".mewcode/config.yaml"


def _summaries(catalog: Catalog) -> list[SkillSummary]:
    """Catalog → UI 层的摘要类型（`command` 包不依赖 skills 包）。"""
    return [
        SkillSummary(s.meta.name, s.meta.description, str(s.source), s.meta.mode)
        for s in catalog.list()
    ]


def _drop_conflicting_skills(catalog: Catalog, cmd_reg) -> None:  # noqa: ANN001
    """与内置命令同名/撞别名的 Skill 不加载（docs/ch11 F16）。

    被丢掉的不只是命令注册——Skill 本身也从 Catalog 移除，`/skill` 与
    LoadSkill 都看不到它。内置命令的可靠性优先于 Skill 的可定制性。
    """
    for name in list(catalog.names()):
        if cmd_reg.lookup(name) is not None:
            print(f"skill {name} conflicts with builtin command, skipped", file=sys.stderr)
            catalog.remove(name)


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

        # ---- Hook 系统装配（docs/ch12 T22）----
        # 在权限引擎之后加载（hook 条件与权限规则共用匹配器）；加载错误只 stderr，
        # 不阻断启动（N1/N9）。引擎交给 runtime 与 App 两个使用方。
        hook_engine = hook.load(root)
        runtime.hook_engine = hook_engine

        # ---- Skill 系统装配（docs/ch11 T28）----
        # 顺序有讲究：先扫 Catalog，再注册两个 Skill 工具，然后才能做 fail-fast
        # 依赖检查（F15 要求检查时 MCP 工具已在册），最后才注册 Skill 命令。
        catalog = Catalog.load(root)
        active = runtime.active_skills
        registry.register(LoadSkillTool(catalog, active, registry))
        registry.register(InstallSkillTool(catalog, root))
        for issue in catalog.validate_tools(registry):
            print(
                f'skill {issue.skill_name}: allowed_tool "{issue.tool_name}" '
                "not registered, skipped",
                file=sys.stderr,
            )
            catalog.remove(issue.skill_name)

        executor = Executor(
            catalog,
            registry,
            engine,
            __version__,
            runtime,
            instruction_text=instruction_text,
            memory_text=memory_text,
            # provider 落地：单 provider 此处即可定；多 provider 待 TUI 选中后
            # 由 App 调 executor.bind() 补上（fork 分支才用得到）
            provider=new_provider(cfg.providers[0]) if len(cfg.providers) == 1 else None,
            provider_config=cfg.providers[0] if len(cfg.providers) == 1 else None,
        )

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
            catalog=catalog,
            executor=executor,
            hook_engine=hook_engine,
        )
        # 内置命令已在 App 构造期注册完，此时才能做 F16 的名字冲突检查：
        # 与内置命令同名/撞别名的 Skill 直接不加载（保护内置命令的可靠性）
        _drop_conflicting_skills(catalog, app.cmd_registry)
        register_skills_as_commands(app.cmd_registry, _summaries(catalog), executor)

        try:
            await app.run_async()
        except KeyboardInterrupt:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"程序异常: {exc}", file=sys.stderr)
            return 1

        # 退出兜底：Ctrl+C / 直接结束不会走 /exit 的 SessionEnd，这里补一次
        # （docs/ch12 T22）。用不依赖 App 状态的最小 payload——此时 App 可能已拆。
        await hook_engine.dispatch(
            Event.SESSION_END,
            {
                "event": Event.SESSION_END.value,
                "session_id": runtime.session.session_id,
                "cwd": root,
                "mode": str(engine.start_mode),
            },
        )
    finally:
        await mcp_mgr.close()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))
