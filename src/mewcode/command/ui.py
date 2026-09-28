"""UI 抽象层（docs/ch10 T4）：handler 操作 TUI 的唯一通道 + 测试桩。

handler 只依赖本协议（F33/F34），不直接持有 Textual App 引用；MewCodeApp
实现全部方法后可作为 ui 传入。NopUI 是零值测试桩，供 command 包单测使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mewcode.llm import Message
from mewcode.permission import Mode


@dataclass(frozen=True)
class SkillSummary:
    """`/skill` 列表与 UI 查询用的一行 Skill 摘要（docs/ch11 T20）。

    放在 command 包而不是 skills 包，是为了让 UI 协议的契约自洽；
    `source` / `mode` 本期不展示（F34），保留给后续 UI 扩展。
    """

    name: str
    description: str
    source: str = ""
    mode: str = ""


class UI(Protocol):
    """命令 handler 可用的界面能力最小面。"""

    # 输出（推入 scrollback）
    def println(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    # 权限模式
    def mode(self) -> Mode: ...
    def set_mode(self, m: Mode) -> None: ...

    # 对话注入（Kind.PROMPT 使用）：display_label 显示在 scrollback，
    # preset_prompt 是实际写入 conversation/JSONL 的文本
    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    # /status 与 /memory 等只读查询
    def usage_in(self) -> int: ...
    def usage_out(self) -> int: ...
    def model_name(self) -> str: ...
    def cwd(self) -> str: ...
    def tool_count(self) -> int: ...
    def memory_files(self) -> list[str]: ...
    def session_path(self) -> str: ...
    def session_id(self) -> str: ...

    # 影响界面动作
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    def open_resume_menu(self) -> None: ...
    def clear_and_new_session(self) -> None: ...

    # 状态机查询（N3a：UI/PROMPT 命令仅在 idle 可执行）
    def idle(self) -> bool: ...

    # Skill 相关（docs/ch11 T20，N11）
    def list_catalog_skills(self) -> list[SkillSummary]: ...
    def list_active_skills(self) -> list[str]: ...
    def clear_active_skills(self) -> None: ...
    def append_assistant_message(self, text: str) -> None: ...
    def recent_messages(self, n: int) -> list[Message]: ...
    def all_messages(self) -> list[Message]: ...


class NopUI:
    """测试桩：所有写入方法 no-op、所有查询返回零值。"""

    def println(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...

    def mode(self) -> Mode:
        return Mode.DEFAULT

    def set_mode(self, m: Mode) -> None: ...

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    def usage_in(self) -> int:
        return 0

    def usage_out(self) -> int:
        return 0

    def model_name(self) -> str:
        return ""

    def cwd(self) -> str:
        return ""

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return ""

    def session_id(self) -> str:
        return ""

    def quit(self) -> None: ...

    def force_compact(self) -> None: ...

    def open_resume_menu(self) -> None: ...

    def clear_and_new_session(self) -> None: ...

    def idle(self) -> bool:
        return True

    # Skill 相关零值实现（N11）
    def list_catalog_skills(self) -> list[SkillSummary]:
        return []

    def list_active_skills(self) -> list[str]:
        return []

    def clear_active_skills(self) -> None: ...

    def append_assistant_message(self, text: str) -> None: ...

    def recent_messages(self, n: int) -> list[Message]:
        return []

    def all_messages(self) -> list[Message]:
        return []
