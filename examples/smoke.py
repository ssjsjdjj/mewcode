"""端到端 smoke：跑一轮多轮任务，打印每轮用量（含缓存写/读）。

用法：python examples/smoke.py（读取 .mewcode/config.yaml）
"""

from __future__ import annotations

import asyncio
import sys

from mewcode import __version__
from mewcode.agent import Agent, SessionRuntime
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.permission import Mode, new_engine
from mewcode.config import load
from mewcode.conversation import Conversation
from pathlib import Path

from mewcode.llm import new_provider
from mewcode.tool import new_default_registry


async def main() -> None:
    cfg = load(".mewcode/config.yaml")
    provider = new_provider(cfg.providers[0])
    registry = new_default_registry()
    engine, _ = new_engine(str(Path.cwd().resolve()))
    # smoke 场景固定 200000（docs/ch08 T32）
    runtime = SessionRuntime(
        ContentReplacementState(),
        RecoveryState(),
        CompactCircuitBreaker(),
        new_session_context(str(Path.cwd())),
        context_window=200000,
    )
    agent = Agent(provider, registry, __version__, engine, runtime=runtime)
    conv = Conversation()

    async def one_round(text: str) -> None:
        conv.add_user(text)
        async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event()):
            if ev.usage is not None:
                u = ev.usage
                print(
                    f"[usage] in={u.input} out={u.output} "
                    f"cache_write={u.cache_write} cache_read={u.cache_read}"
                )

    print(f"provider={provider.name} model={provider.model}")
    print("--- 第一轮 ---")
    await one_round("读 docs/ch03/spec.md，再用一句话概括它讲的内容（不写文件）")
    print("--- 第二轮（复用同一会话，观察缓存命中）---")
    await one_round("刚才概括的 spec 是第几章的？只用一句话回答")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
