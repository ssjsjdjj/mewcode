"""JSONL 会话写入器（docs/ch09 F15/F16）。

conversation.jsonl 只做追加写，崩溃最多丢最后一行。每次 append 后
flush + fsync 刷盘；threading.Lock 保证多协程/线程追加原子性。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from mewcode.llm import Message


@dataclass
class Entry:
    """JSONL 中一行的 dataclass 表示（docs/ch09 F11）。"""

    role: str = ""  # "user" / "assistant" / "tool"
    content: str = ""
    tool_calls: list[dict] | None = None  # 仅 assistant，结构同 llm.ToolCall
    tool_results: list[dict] | None = None  # 仅 tool，结构同 llm.ToolResult
    ts: int = 0  # 写入时刻 Unix 秒
    model: str | None = None  # 仅第一条消息携带
    type: str | None = None  # "compact" 或省略


class Writer:
    """向 conversation.jsonl 追加写入的会话存档。"""

    def __init__(self, session_dir: str) -> None:
        self._session_dir = session_dir
        Path(session_dir).mkdir(parents=True, exist_ok=True)
        self._model = ""
        self._first_written = True  # 新会话第一条消息携带 model
        self._open()

    @classmethod
    def open_existing(cls, session_dir: str) -> "Writer":
        """打开已有会话（恢复场景）：不创建目录，追加模式。"""
        writer = cls.__new__(cls)
        writer._session_dir = session_dir
        writer._model = ""
        # 已有存档的首条 model 早已写入，恢复后的追加不再视为"首条"
        writer._first_written = False
        writer._open()
        return writer

    def _open(self) -> None:
        self._lock = threading.Lock()
        self._path = str(Path(self._session_dir) / "conversation.jsonl")
        self._file = open(self._path, "ab")

    @property
    def session_dir(self) -> str:
        return self._session_dir

    @property
    def path(self) -> str:
        """当前会话存档 JSONL 的绝对路径（docs/ch10 T0b，/session 命令数据源）。"""
        return self._path

    def set_model(self, model: str) -> None:
        """provider 选定后记录模型名，供首条消息写入。"""
        self._model = model

    def append(self, msg: Message, model: str, is_first: bool) -> None:
        """追加一条消息；is_first 时填充 model 字段。"""
        entry: dict = {"role": msg.role, "ts": int(time.time())}
        if msg.content:
            entry["content"] = msg.content
        if msg.tool_calls:
            entry["tool_calls"] = [asdict(tc) for tc in msg.tool_calls]
        if msg.tool_results:
            entry["tool_results"] = [asdict(tr) for tr in msg.tool_results]
        if is_first and model:
            entry["model"] = model
        self._write_line(entry)

    def write_compact_marker(self) -> None:
        """写入压缩标记行（docs/ch09 F12）。"""
        self._write_line({"type": "compact", "ts": int(time.time())})

    def append_all(self, msgs: list[Message]) -> None:
        """压缩后逐条追加新消息。"""
        for msg in msgs:
            self.append(msg, model="", is_first=False)

    def on_append(self, msg: Message) -> None:
        """Conversation 追加回调：内部包装 append，处理首条 model。"""
        is_first = self._first_written
        self._first_written = False
        self.append(msg, model=self._model, is_first=is_first)

    def on_replace(self, msgs: list[Message]) -> None:
        """Conversation 整体替换回调：压缩标记 + 追加新消息（docs/ch09 F12）。"""
        self.write_compact_marker()
        self.append_all(msgs)

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _write_line(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            os.fsync(self._file.fileno())
