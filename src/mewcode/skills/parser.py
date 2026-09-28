"""SKILL.md 与 tool.json 解析（docs/ch11 T2）。

单个 Skill 解析失败由调用方（Catalog）捕获后跳过，不影响其它 Skill（F11）。

命名规则有两套，别混用（docs 把两者写成同一条规则，实际不同）：
- **Skill 名**用连字符：它同时是 Slash 命令名，`^[a-z][a-z0-9-]*$`（F3）
- **工具名**用下划线：与项目既有工具（`read_file` / `load_skill`）保持一致，
  `^[a-z][a-z0-9_]*$`——AC11 的样例工具名 `parse_resume` 就是下划线形式
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from .types import Skill, SkillMeta, SkillSource, ToolSpec

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NAME_MAX_LEN = 32

_VALID_MODES = ("inline", "fork")
_VALID_FORK_CONTEXTS = ("none", "recent", "full")


def _warn(msg: str) -> None:
    print(f"[skills] warn: {msg}", file=sys.stderr)


def parse_frontmatter_and_body(data: str) -> tuple[dict, str]:
    """切出 `---` 包围的 frontmatter 与其余正文。"""
    if not data.lstrip("﻿").startswith("---"):
        raise ValueError("SKILL.md must start with a '---' frontmatter block")
    lines = data.lstrip("﻿").split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("unterminated frontmatter block (missing closing '---')")
    parsed = yaml.safe_load("\n".join(lines[1:end]))
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return parsed, body


def parse_tool_json(data: bytes, base_dir: Path) -> list[ToolSpec]:
    """解析 `tool.json` 的 `{"tools": [...]}` 结构（F10）。"""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"tool.json is not valid JSON: {exc}") from exc
    items = raw.get("tools") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("tool.json must be an object with a 'tools' array")

    specs: list[ToolSpec] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"tool.json tools[{i}] must be an object")
        name = str(item.get("name") or "").strip()
        if not TOOL_NAME_RE.match(name):
            raise ValueError(f"tool.json tools[{i}]: invalid tool name {name!r}")
        command = item.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) and x for x in command)
        ):
            raise ValueError(f"tool.json tools[{i}]: command must be a non-empty string array")
        schema = item.get("input_schema")
        if not isinstance(schema, dict):
            raise ValueError(f"tool.json tools[{i}]: input_schema must be an object")
        specs.append(
            ToolSpec(
                name=name,
                description=str(item.get("description") or ""),
                input_schema=schema,
                command=[str(x) for x in command],
                base_dir=base_dir,
            )
        )
    return specs


def _build_meta(raw: dict, dir_path: Path) -> SkillMeta:
    """校验并规整 frontmatter；非法值按 F6/F7 打 warning 后回退默认。"""
    name = str(raw.get("name") or "").strip()
    if not name or len(name) > NAME_MAX_LEN or not SKILL_NAME_RE.match(name):
        raise ValueError(
            f"invalid skill name {name!r} in {dir_path} (want ^[a-z][a-z0-9-]*$, 1-32)"
        )

    description = str(raw.get("description") or "").strip()
    if not description:
        raise ValueError(f"skill {name}: description is required")

    allowed_raw = raw.get("allowed_tools")
    if allowed_raw is None:
        allowed: list[str] = []
    elif isinstance(allowed_raw, list):
        allowed = [str(x).strip() for x in allowed_raw if str(x).strip()]
    else:
        raise ValueError(f"skill {name}: allowed_tools must be a list")

    mode = str(raw.get("mode") or "").strip() or "inline"
    if mode not in _VALID_MODES:
        _warn(f"skill {name}: unknown mode {mode!r}, falling back to inline")
        mode = "inline"

    fork_context = str(raw.get("fork_context") or "").strip() or "none"
    if fork_context not in _VALID_FORK_CONTEXTS:
        _warn(f"skill {name}: unknown fork_context {fork_context!r}, falling back to none")
        fork_context = "none"

    model_raw = raw.get("model")
    model = str(model_raw).strip() if model_raw else None

    return SkillMeta(
        name=name,
        description=description,
        allowed_tools=allowed,
        mode=mode,  # type: ignore[arg-type]
        fork_context=fork_context,  # type: ignore[arg-type]
        model=model,
    )


def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill:
    """解析一个 Skill 目录 → `Skill`；缺 SKILL.md 抛 `FileNotFoundError`（F1）。"""
    skill_md = dir_path / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"no SKILL.md in {dir_path}")

    raw = skill_md.read_text(encoding="utf-8")
    meta_dict, body = parse_frontmatter_and_body(raw)
    meta = _build_meta(meta_dict, dir_path)

    resolved = dir_path.resolve()
    tool_specs: list[ToolSpec] = []
    tool_json = dir_path / "tool.json"
    if tool_json.is_file():
        tool_specs = parse_tool_json(tool_json.read_bytes(), resolved)

    return Skill(
        meta=meta,
        prompt_body=body,
        source_dir=resolved,
        source=source,
        tool_specs=tool_specs,
    )


def read_skill_body(skill: Skill) -> str:
    """从磁盘重读 SKILL.md 正文，取用户改后的最新版（F23）。

    读失败（文件被删/权限/格式损坏）回退到启动期缓存并告警——一次磁盘错误
    不该中断已加载的 Skill（N5）。LoadSkill 工具与 Skill 执行器共用本函数。
    """
    try:
        raw = (skill.source_dir / "SKILL.md").read_text(encoding="utf-8")
        _, body = parse_frontmatter_and_body(raw)
        return body
    except (OSError, ValueError) as exc:
        _warn(f"skill {skill.meta.name}: re-read failed ({exc}), using cached body")
        return skill.prompt_body
