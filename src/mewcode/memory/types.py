"""记忆系统类型定义（docs/ch09 F17/F18）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NoteType(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


@dataclass
class Note:
    """一条笔记的内存表示（docs/ch09 F17）。"""

    type: NoteType
    title: str
    slug: str
    content: str
    filename: str
    created: datetime
    updated: datetime


@dataclass
class UpdateAction:
    """LLM 返回的单条操作（docs/ch09 F18）。"""

    action: str  # "create"/"update"/"delete"
    level: str  # "project"/"user"
    type: str = ""  # NoteType（create 时必需）
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""  # update/delete 时必需
