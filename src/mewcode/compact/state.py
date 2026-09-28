"""上下文管理的跨轮会话状态（ch08；ch09 T1 会话 ID 新格式 + session_dir）。

包含：SessionContext（会话目录）、ContentReplacementState（工具结果替换账本）、
CompactCircuitBreaker（自动压缩熔断）、RecoveryState（最近读文件追踪）。
"""

from __future__ import annotations

import copy
import logging
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

logger = logging.getLogger(__name__)

_ID_TS_FORMAT = "%Y%m%d-%H%M%S"


@dataclass
class SessionContext:
    """一次 mewcode 会话的磁盘上下文（docs/ch09 F9/F10）。"""

    session_id: str  # 形如 "YYYYMMDD-HHMMSS-xxxx"
    session_dir: str  # <workspace>/.mewcode/sessions/<session_id>
    spill_dir: str  # session_dir + "/tool-results"（工具结果落盘目录）


def _new_session_id() -> str:
    """生成形如 "YYYYMMDD-HHMMSS-xxxx" 的会话 ID（docs/ch09 F9）。

    前 15 位为进程启动时刻的本地时间，xxxx 为 4 字符随机十六进制后缀防同秒碰撞。
    优先用 secrets.token_hex；失败（极罕见）降级到基于 time 的随机字节并告警。
    """
    ts = datetime.now().strftime(_ID_TS_FORMAT)
    try:
        hex_str = secrets.token_hex(2)
    except Exception:  # noqa: BLE001 - secrets 失败为极罕见路径，降级即可
        logger.warning("secrets.token_hex 失败，使用 time 降级生成会话 ID")
        hex_str = random.Random(time.time()).randbytes(2).hex()
    return f"{ts}-{hex_str}"


def new_session_context(workspace: str) -> SessionContext:
    """创建新会话：生成 ID 并确保工具结果落盘目录存在。"""
    session_id = _new_session_id()
    session_dir = str(Path(workspace) / ".mewcode" / "sessions" / session_id)
    spill_dir = str(Path(session_dir) / "tool-results")
    Path(spill_dir).mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, session_dir=session_dir, spill_dir=spill_dir)


def open_session_context(workspace: str, session_id: str) -> SessionContext:
    """打开已有会话（docs/ch09 F22 恢复场景）：不创建目录，缺目录抛 FileNotFoundError。"""
    session_dir = str(Path(workspace) / ".mewcode" / "sessions" / session_id)
    if not Path(session_dir).is_dir():
        raise FileNotFoundError(f"会话目录不存在: {session_dir}")
    spill_dir = str(Path(session_dir) / "tool-results")
    return SessionContext(session_id=session_id, session_dir=session_dir, spill_dir=spill_dir)


def parse_session_time(session_id: str) -> datetime:
    """从 ID 前 15 位解析 YYYYMMDD-HHMMSS；格式不符抛 ValueError（供清理/排序）。"""
    return datetime.strptime(session_id[:15], _ID_TS_FORMAT)


class ContentReplacementState:
    """工具结果替换决策账本：同一 tool_use_id 的替换决策冻结一次，跨轮复用。

    # 无需显式锁——Python asyncio 单线程事件循环保证串行
    """

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def decide_once(
        self,
        tool_use_id: str,
        original: str,
        decide: Callable[[], tuple[str, str]],
    ) -> str:
        """持锁完成"查账本 → 决策 → 写账本"原子操作。

        若 id 已 Seen：直接返回账本中存量结果（kept 返回原 content，
        replaced 返回 _replacements[id]）。
        若 id 未 Seen：调 decide() 回调（仍持锁）：
          - 回调返回 ("kept", _)：写 _seen_ids，不写 _replacements；返回原 content。
          - 回调返回 ("replaced", preview)：写 _seen_ids + _replacements；返回 preview。
          - 回调返回 ("skip", _)：既不写 _seen_ids 也不写 _replacements；返回原
            content（下一轮重试）。
        """
        if tool_use_id in self._seen_ids:
            return self._replacements.get(tool_use_id, original)
        decision, preview = decide()
        if decision == "kept":
            self._seen_ids.add(tool_use_id)
            return original
        if decision == "replaced":
            self._seen_ids.add(tool_use_id)
            self._replacements[tool_use_id] = preview
            return preview
        # "skip"：不写账本，下一轮重试
        return original


class CompactCircuitBreaker:
    """自动压缩连续失败熔断器。

    # 无需显式锁——Python asyncio 单线程事件循环保证串行
    """

    def __init__(self) -> None:
        self._consecutive_failures = 0

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1

    def tripped(self) -> bool:
        return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


@dataclass
class FileReadRecord:
    """一次 read_file 工具调用的内容快照（供压缩恢复附件使用）。"""

    path: str  # 绝对路径
    content: str
    timestamp: datetime


class RecoveryState:
    """最近读文件追踪：key 为绝对路径，值带读取时间。

    # 无需显式锁——Python asyncio 单线程事件循环保证串行
    """

    def __init__(self) -> None:
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        """记录一次文件读取；非绝对路径先 resolve 归一。"""
        if not Path(path).is_absolute():
            path = str(Path(path).resolve())
        self._files[path] = FileReadRecord(
            path=path,
            content=content,
            timestamp=datetime.now(),
        )

    def snapshot(self) -> list[FileReadRecord]:
        """按读取时间倒序返回快照拷贝。"""
        records = [copy.copy(rec) for rec in self._files.values()]
        return sorted(records, key=lambda rec: rec.timestamp, reverse=True)
