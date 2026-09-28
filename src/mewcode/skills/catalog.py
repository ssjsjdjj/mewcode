"""Skill Catalog：三层路径扫描、同名覆盖、依赖 fail-fast（docs/ch11 T4/T5）。

扫描顺序即覆盖顺序，后扫到的同名 Skill 替换前者（F13）：

1. 内置（`importlib.resources` 从 `mewcode.skills.builtin` 读）
2. 用户级 `~/.mewcode/skills/`
3. 项目级 `<work_dir>/.mewcode/skills/`

容错策略两层相反（N4）：**内置**解析失败直接 raise（属于代码 bug，不该被吞），
用户级/项目级解析失败只打 warning 并跳过单个 Skill（F11/F14）。
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from .parser import parse_skill_dir
from .types import Skill, SkillSource

if TYPE_CHECKING:  # 避免 tool ←→ skills 的运行时循环依赖
    from mewcode.tool import Registry

# fail-fast 检查中视为「总是可用」的工具名（F15）
_ALWAYS_AVAILABLE = frozenset({"load_skill", "install_skill"})

BUILTIN_PACKAGE = "mewcode.skills.builtin"


def _warn(msg: str) -> None:
    print(f"[skills] warn: {msg}", file=sys.stderr)


@dataclass
class ValidationIssue:
    """一条 `allowed_tools` 引用了未注册工具的记录（F15）。"""

    skill_name: str
    tool_name: str


def user_skills_dir() -> Path:
    """`~/.mewcode/skills/`；`Path.home()` 取不到时退回当前目录下的同名路径。"""
    try:
        return Path.home() / ".mewcode" / "skills"
    except (RuntimeError, OSError):  # 极端环境下 home 不可解析
        return Path(".mewcode") / "skills"


class Catalog:
    """已加载 Skill 的集合，按 name 索引、按字典序稳定迭代。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, Skill] = {}
        self._order: list[str] = []

    def register(self, s: Skill) -> None:
        """登记一个 Skill；同名覆盖，位置不变（F13）。"""
        name = s.meta.name
        with self._lock:
            if name in self._by_name:
                self._by_name[name] = s
                return
            self._by_name[name] = s
            self._order.append(name)
            self._order.sort()

    def remove(self, name: str) -> None:
        """剔除一个 Skill（fail-fast 不合格项、命令名冲突项用）。"""
        with self._lock:
            if name not in self._by_name:
                return
            del self._by_name[name]
            self._order.remove(name)

    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> list[Skill]:
        with self._lock:
            return [self._by_name[n] for n in self._order]

    def names(self) -> list[str]:
        with self._lock:
            return list(self._order)

    def __len__(self) -> int:
        with self._lock:
            return len(self._order)

    @classmethod
    def load(cls, work_dir: Path | str) -> Catalog:
        """按内置 → 用户级 → 项目级顺序扫描（F12）。"""
        catalog = cls()
        catalog._load_builtin()
        catalog._load_dir(user_skills_dir(), SkillSource.USER)
        catalog._load_dir(Path(work_dir) / ".mewcode" / "skills", SkillSource.PROJECT)
        return catalog

    def reload(self, work_dir: Path | str) -> None:
        """重新扫描三层路径并原子替换内部状态（F17，InstallSkill 后用）。"""
        fresh = Catalog.load(work_dir)
        with self._lock:
            self._by_name = fresh._by_name
            self._order = fresh._order

    def _load_builtin(self) -> None:
        """载入随包分发的内置 Skill；任何解析失败都 raise（N4）。"""
        base = files(BUILTIN_PACKAGE)
        for entry in sorted(base.iterdir(), key=lambda e: e.name):
            if not entry.is_dir() or not entry.joinpath("SKILL.md").is_file():
                continue
            path = Path(str(entry))
            if not path.is_dir():
                # 资源未被解压成真实目录（zipimport）；tool.json 的脚本 exec 需要真实路径
                _warn(f"builtin skill {entry.name} not on a real filesystem, skipped")
                continue
            self.register(parse_skill_dir(path, SkillSource.BUILTIN))

    def _load_dir(self, base: Path, source: SkillSource) -> None:
        """扫描一个目录下的直接子目录；单个失败只跳过自身（F11/F14）。"""
        try:
            if not base.is_dir():
                return  # 目录不存在静默跳过（F14）
            children = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError as exc:
            _warn(f"cannot scan {base}: {exc}")
            return

        for child in children:
            if not (child / "SKILL.md").is_file():
                _warn(f"{child} has no SKILL.md, skipped")
                continue
            try:
                self.register(parse_skill_dir(child, source))
            except (ValueError, OSError) as exc:
                _warn(f"skill {child.name} skipped: {exc}")

    def validate_tools(self, reg: Registry) -> list[ValidationIssue]:
        """检查每条 `allowed_tools` 是否都有对应工具（F15）。

        `load_skill` / `install_skill` 视为总是可用；Skill 自己 `tool.json`
        声明的专属工具也算可用（它们在被 LoadSkill 激活时才注册进来）。
        """
        issues: list[ValidationIssue] = []
        for skill in self.list():
            own = {spec.name for spec in skill.tool_specs}
            for tool_name in skill.meta.allowed_tools:
                if tool_name in _ALWAYS_AVAILABLE or tool_name in own:
                    continue
                if reg.get(tool_name) is None:
                    issues.append(ValidationIssue(skill.meta.name, tool_name))
        return issues
