"""InstallSkill 工具：从 URL 安装第三方 Skill 包（docs/ch11 T17，F30–F33）。

**不是**系统工具、**不是**只读——它有外部副作用（下载 + 写盘），必须走权限授权
（F33）。装完调 `Catalog.reload`，新的 `/<name>` 命令立即生效，无需重启（F32）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import Result

if TYPE_CHECKING:
    from mewcode.skills import Catalog


class InstallSkillTool:
    def __init__(self, catalog: Catalog, work_dir: Path | str) -> None:
        self._catalog = catalog
        self._work_dir = work_dir

    def name(self) -> str:
        return "install_skill"

    def description(self) -> str:
        return (
            "从 URL 安装一个 Skill 包（.zip）。zip 内需有唯一的顶层目录，"
            "目录名即 Skill 名且需满足小写字母/数字/连字符，内含 SKILL.md。"
            "安装到 ~/.mewcode/skills/ 并立即生效。"
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def deferrable(self) -> bool:
        return False

    @property
    def is_system(self) -> bool:
        return False

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "指向 Skill zip 的 URL"}},
            "required": ["source"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        source = data.get("source")
        if not isinstance(source, str) or not source:
            return Result(content="缺少必填参数 source", is_error=True)

        from mewcode.skills.install import install_from_url

        try:
            name = await install_from_url(source, self._catalog, self._work_dir)
        except Exception as exc:  # noqa: BLE001 —— 下载/解压/校验失败统一转结构化错误
            return Result(content=f"安装 Skill 失败: {exc}", is_error=True)

        return Result(content=f"Skill {name} installed to ~/.mewcode/skills/{name}.")
