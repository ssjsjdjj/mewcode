"""LoadSkill 工具：把某个 Skill 的完整 SOP 钉进环境上下文（docs/ch11 T16，F23）。

是**系统工具**且**只读**——两个标记都必要：
- `read_only=True` → 权限引擎归为 READ 类，任意模式下自动放行、永不弹审批（F23/N4/AC7）
- `is_system=True` → 不受 `allowed_tools` 白名单约束，任何子集里都可见
  （嵌套 Skill 场景靠这条成立）
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from . import Result

if TYPE_CHECKING:
    from mewcode.skills import ActiveSkills, Catalog
    from mewcode.tool import Registry


def _warn(msg: str) -> None:
    print(f"[skills] warn: {msg}", file=sys.stderr)


class LoadSkillTool:
    def __init__(self, catalog: Catalog, active: ActiveSkills, registry: Registry) -> None:
        self._catalog = catalog
        self._active = active
        self._registry = registry

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return (
            "激活一个 Skill：把它的完整 SOP 钉到环境上下文，并注册其专属工具。"
            "当用户意图与可用 Skill 列表中的某项匹配时，先调用本工具再执行，"
            "不要凭 Skill 的名字猜测其内容。"
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def deferrable(self) -> bool:
        return False

    @property
    def is_system(self) -> bool:
        return True

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "要激活的 Skill 名"}},
            "required": ["name"],
        }

    def _fresh_body(self, skill: Any) -> str:
        """从磁盘重读 SKILL.md 取最新正文；读失败回退启动期缓存（N5）。"""
        from mewcode.skills import read_skill_body

        return read_skill_body(skill)

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        name = data.get("name")
        if not isinstance(name, str) or not name:
            return Result(content="缺少必填参数 name", is_error=True)

        skill = self._catalog.get(name)
        if skill is None:
            return Result(content=f"unknown skill: {name}", is_error=True)

        self._active.activate(skill.meta.name, self._fresh_body(skill))

        from .skill_tool import new_skill_tool

        for spec in skill.tool_specs:
            self._registry.register_skill_tool(
                new_skill_tool(
                    spec.name,
                    spec.description,
                    spec.input_schema,
                    spec.command,
                    spec.base_dir,
                )
            )

        return Result(
            content=(
                f"Skill {name} activated. SOP pinned to env context. "
                f"{len(skill.tool_specs)} specialized tools registered."
            )
        )
