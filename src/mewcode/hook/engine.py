"""事件分派引擎（docs/ch12 T10，F27–F29/F32/F33）。

按规则声明顺序遍历匹配的 hook：同步 hook 串行执行（N3），`async: true` 的丢到后台
task 里立即继续。拦截类事件下遇到第一条表达拦截的 hook 就中断后续——剩下那些本来
也会被这次拦截跳过，没必要执行。

`only_once` 的集合是**会话内存态**：`/clear` 与 `/resume` 换会话时由调用方清空
（N5），进程退出不落盘。
"""

from __future__ import annotations

import asyncio
import sys

from .event import Event, is_blocking
from .executor import Executor
from .matcher import eval_condition
from .rule import DispatchResult, Payload, Rule


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


class Engine:
    """持有已加载规则，按事件分派动作。"""

    def __init__(
        self,
        rules: list[Rule],
        sources: list[str],
        executor: Executor | None = None,
    ) -> None:
        self._rules = list(rules)
        self._sources = list(sources)
        self._executor = executor or Executor()
        self._once_fired: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def rules(self) -> list[Rule]:
        """规则副本（防外部改动；`/hooks` 与测试用）。"""
        return list(self._rules)

    @property
    def sources(self) -> list[str]:
        """加载来源文件列表（`/hooks` 展示用）。"""
        return list(self._sources)

    def has_rules(self) -> bool:
        return bool(self._rules)

    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult:
        """分派一次事件；返回待注入的 prompt 与拦截判定。"""
        result = DispatchResult()
        blocking_event = is_blocking(event)

        for rule in self._rules:
            if rule.event is not event:
                continue
            if rule.only_once and await self._is_fired(rule.name):
                continue
            if not eval_condition(rule.condition, payload):
                continue

            if rule.asyncio_mode:
                # 异步不参与拦截判定，也不进 reminder 队列（F28）
                asyncio.create_task(self._executor.run(rule, payload, blocking=False))
                if rule.only_once:
                    await self._mark_fired(rule.name)
                continue

            outcome = await self._executor.run(rule, payload, blocking=blocking_event)
            if outcome.err is not None:
                _warn(f"[hook {rule.name}] {event.value} failed: {outcome.err}")
                continue  # 失败不算命中：不注入、不拦截、不标记 only_once（F29）
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            if outcome.blocked and blocking_event:
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
            if rule.only_once:
                await self._mark_fired(rule.name)

        return result

    async def reset_for_new_session(self) -> None:
        """清空 only_once 记录（`/clear`、`/resume` 换会话时调，N5）。"""
        async with self._lock:
            self._once_fired.clear()

    async def _is_fired(self, name: str) -> bool:
        async with self._lock:
            return name in self._once_fired

    async def _mark_fired(self, name: str) -> None:
        async with self._lock:
            self._once_fired.add(name)
