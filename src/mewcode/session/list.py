"""会话列表扫描（docs/ch09 F13）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mewcode.compact.state import parse_session_time

TITLE_MAX_LEN = 50


@dataclass
class SessionInfo:
    """会话列表中一项的摘要信息（docs/ch09 F13）。"""

    id: str  # session ID（目录名）
    title: str  # 第一条 user 消息内容（截断到 50 字符）
    modified_at: datetime  # 最后修改时间
    model: str  # 模型标签
    size: int  # JSONL 文件大小（字节）
    dir: str  # 会话目录绝对路径


def _first_user_title(jsonl: Path) -> str:
    """取第一条 role=="user" 消息的 content 做标题；找不到返回空串。"""
    title = ""
    try:
        with open(jsonl, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # 坏行跳过
                if obj.get("role") == "user":
                    title = str(obj.get("content") or "")
                    break
    except OSError:
        return ""
    title = " ".join(title.split())  # 折叠换行/空白成单行便于展示
    return title[:TITLE_MAX_LEN]


def _first_model(jsonl: Path) -> str:
    """取首条消息的 model 字段；读失败返回空串。"""
    try:
        with open(jsonl, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                return str(obj.get("model") or "")
    except OSError:
        pass
    return ""


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """扫描 sessions_dir，返回按修改时间倒序的会话列表。

    只返回目录名可解析为新格式且存在 conversation.jsonl 的会话；
    旧格式目录、无存档目录、统计失败的目录静默跳过。
    """
    base = Path(sessions_dir)
    if not base.is_dir():
        return []
    items: list[SessionInfo] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式目录跳过（docs/ch09 F13）
        jsonl = child / "conversation.jsonl"
        if not jsonl.is_file():
            continue
        try:
            st = jsonl.stat()
        except OSError:
            continue
        items.append(
            SessionInfo(
                id=child.name,
                title=_first_user_title(jsonl),
                modified_at=datetime.fromtimestamp(st.st_mtime),
                model=_first_model(jsonl),
                size=st.st_size,
                dir=str(child.resolve()),
            )
        )
    items.sort(key=lambda info: info.modified_at, reverse=True)
    return items
