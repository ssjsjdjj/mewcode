"""记忆管理器：两级 Store 编排与异步 LLM 更新（docs/ch09 F20-F23）。

ch10 T0a：新增 list_files，为 /memory 命令提供两级记忆文件名清单。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from mewcode.llm import Message, Provider, Request, System
from mewcode.memory.prompts import MEMORY_UPDATE_SYSTEM_PROMPT
from mewcode.memory.store import Store
from mewcode.memory.types import UpdateAction

logger = logging.getLogger(__name__)

_INDEX_MAX_BYTES = 25 * 1024  # 合并索引上限 25KB（docs/ch09 F20）
_TRUNCATE_MARKER = "\n(index truncated)"


def _format_message(msg: Message) -> str:
    """最近消息 → 一行文本，供记忆更新 prompt 拼接。"""
    role = msg.role
    content = msg.content or ""
    if msg.tool_calls:
        names = ", ".join(tc.name for tc in msg.tool_calls)
        return f"[{role}] 调用工具: {names}\n{content}"
    return f"[{role}] {content}"


def _parse_actions(raw: str) -> list[UpdateAction]:
    """解析 LLM 返回的 JSON 数组为 UpdateAction；解析失败返回空列表。

    容忍模型在回复中包裹 ```json 代码块：取第一个 [ 到最后一个 ] 之间的文本。
    """
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    actions: list[UpdateAction] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        if action not in ("create", "update", "delete"):
            continue
        actions.append(
            UpdateAction(
                action=action,
                level=str(item.get("level") or "project"),
                type=str(item.get("type") or ""),
                title=str(item.get("title") or ""),
                slug=str(item.get("slug") or ""),
                content=str(item.get("content") or ""),
                filename=str(item.get("filename") or ""),
            )
        )
    return actions


class Manager:
    """编排项目级和用户级笔记的加载与更新。"""

    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: Provider | None,
        model: str,
    ) -> None:
        self._project_store = Store(project_dir)
        self._user_store = Store(user_dir)
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()  # 防并发更新（docs/ch09 F22）

    def list_files(self) -> tuple[list[str], list[str]]:
        """列出项目层与用户层 memory 目录下的 .md 文件名（含 MEMORY.md），各按字典序。

        目录不存在或其它 OSError 视为空列表，不抛异常（docs/ch10 T0a，/memory 命令数据源）。
        """
        return (self._list_md(self._project_store), self._list_md(self._user_store))

    @staticmethod
    def _list_md(store: Store) -> list[str]:
        try:
            return sorted(p.name for p in Path(store._dir).glob("*.md"))
        except OSError:
            logger.warning("读取记忆目录失败: %s", store._dir)
            return []

    def load_index(self) -> str:
        """合并两级索引：项目级在前、用户级在后；超 25KB 截断加标注。"""
        project = self._project_store.load_index().strip()
        user = self._user_store.load_index().strip()
        merged = "\n\n".join(p for p in (project, user) if p)
        if len(merged.encode("utf-8")) <= _INDEX_MAX_BYTES:
            return merged
        budget = _INDEX_MAX_BYTES - len(_TRUNCATE_MARKER.encode("utf-8"))
        return merged.encode("utf-8")[:budget].decode("utf-8", errors="ignore") + _TRUNCATE_MARKER

    def set_provider(self, provider: Provider, model: str) -> None:
        """延迟设置 provider/model（启动时 provider 未选定，docs/ch09 F21）。"""
        self._provider = provider
        self._model = model

    async def update_async(self, recent_msgs: list[Message]) -> None:
        """根据最近消息异步更新记忆；任何失败仅记日志不上抛。"""
        if self._provider is None:
            return
        async with self._lock:
            try:
                index = self.load_index()
                user_text = (
                    "以下是最近的对话消息：\n\n"
                    + "\n".join(_format_message(m) for m in recent_msgs)
                    + "\n\n现有记忆索引：\n"
                    + (index or "(空)")
                )
                req = Request(
                    messages=[Message(role="user", content=user_text)],
                    tools=[],
                    system=System(stable=MEMORY_UPDATE_SYSTEM_PROMPT, environment=""),
                )
                text_parts: list[str] = []
                async for ev in self._provider.stream(req):
                    if ev.err is not None:
                        raise ev.err
                    if ev.text:
                        text_parts.append(ev.text)
                actions = _parse_actions("".join(text_parts))
                project_actions = [a for a in actions if a.level == "project"]
                user_actions = [a for a in actions if a.level == "user"]
                if project_actions:
                    self._project_store.apply(project_actions)
                if user_actions:
                    self._user_store.apply(user_actions)
            except Exception:  # noqa: BLE001 —— 记忆更新失败不阻断主对话
                logger.exception("记忆更新失败")
