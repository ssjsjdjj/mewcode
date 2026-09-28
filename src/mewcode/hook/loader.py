"""hooks.yaml 加载（docs/ch12 T8，F6–F8/F28）。

两层叠加合并：项目级 `<root>/.mewcode/hooks.yaml` 与用户级 `~/.mewcode/hooks.yaml`
的规则**共同参与**事件分派（不是覆盖关系）。同名 hook 加载期报冲突并跳过后到者,
因此先扫项目级 = 项目级优先（F7）。

所有加载错误一律 stderr 输出后继续——一条写错的 hook 不该让 mewcode 起不来（N1/N9）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from mewcode.permission.matcher import (
    ExactMatcher,
    GlobMatcher,
    Matcher,
    NotMatcher,
    RegexMatcher,
)

from .engine import Engine
from .event import Event, is_blocking, parse_event
from .rule import (
    Action,
    AtomCondition,
    CombineMode,
    Condition,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)

DEFAULT_TIMEOUT = 30.0
_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smh]?)$")
_UNIT_SECONDS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def _skip(name: str, reason: str) -> None:
    _warn(f'hook "{name}": {reason}, skipped')


def parse_duration(s: object) -> float:
    """`30s` / `5m` / `1h` / 数字（秒）→ 秒数；非法抛 ValueError（F18）。"""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        if s < 0:
            raise ValueError(f"negative duration {s!r}")
        return float(s)
    m = _DURATION_RE.match(str(s).strip())
    if not m:
        raise ValueError(f"bad duration {s!r} (want like '30s' / '5m')")
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2)]


# ---- 条件 ----


def _compile_match(spec: object) -> Matcher:
    """结构化 match 规格 → Matcher（F14）。

    只接受 `{type: exact|glob|regex|not, ...}` 形式；hook 条件里的 glob 一律按
    路径语义（段内 `*` 不跨 `/`）——命令串想整串通配请用 regex（T8 的决策）。
    """
    if not isinstance(spec, dict):
        raise ValueError(f"match must be a mapping, got {type(spec).__name__}")
    kind = spec.get("type")
    if kind == "not":
        if "inner" not in spec:
            raise ValueError("not matcher requires 'inner'")
        return NotMatcher(_compile_match(spec["inner"]))
    if kind not in ("exact", "glob", "regex"):
        raise ValueError(f"unknown match type {kind!r} (want exact/glob/regex/not)")
    if "value" not in spec:
        raise ValueError(f"{kind} matcher requires 'value'")
    value = str(spec["value"])
    if kind == "exact":
        return ExactMatcher(value)
    if kind == "glob":
        return GlobMatcher(value, is_command=False)
    return RegexMatcher(value)  # 编译失败抛 re.error，由调用方转成加载错误


def _compile_condition(raw: object) -> Condition | None:
    """`if:` 块 → Condition；缺省/空返回 None（= 无条件，F11）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'if' must be a mapping")
    present = [k for k in ("all_of", "any_of") if k in raw]
    if len(present) > 1:
        raise ValueError("'if' cannot contain both all_of and any_of")
    if not present:
        raise ValueError("'if' must contain all_of or any_of")
    mode = CombineMode(present[0])
    items = raw[present[0]]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{present[0]} must be a non-empty list")
    atoms: list[AtomCondition] = []
    for item in items:
        if not isinstance(item, dict) or "field" not in item:
            raise ValueError("each condition atom needs 'field'")
        if "match" not in item:
            raise ValueError("each condition atom needs 'match'")
        atoms.append(AtomCondition(field=str(item["field"]), matcher=_compile_match(item["match"])))
    return Condition(mode=mode, atoms=tuple(atoms))


# ---- 动作 ----

# 每种动作的必填字段 + 允许出现的字段（多出来的键一律报错，见下）
_REQUIRED = {
    "shell": ("command",),
    "prompt": ("text",),
    "http": ("url",),
    "subagent": ("agent_name", "prompt"),
}
_ALLOWED = {
    "shell": {"type", "command"},
    "prompt": {"type", "text"},
    "http": {"type", "url", "method", "headers", "body"},
    "subagent": {"type", "agent_name", "prompt"},
}


def _compile_action(raw: object) -> Action:
    if not isinstance(raw, dict):
        raise ValueError("'action' must be a mapping")
    kind = raw.get("type")
    if kind not in _REQUIRED:
        raise ValueError(f"unknown action type {kind!r}")
    for field_name in _REQUIRED[kind]:
        if not raw.get(field_name):
            raise ValueError(f"action {kind!r} requires '{field_name}'")

    # 未知键报错而不是忽略：`timeout` / `only_once` 这类字段是**规则级**的，
    # 写在 action 里会被静默忽略——用户以为设了超时其实没设，这种坑必须喊出来。
    extra = set(raw) - _ALLOWED[kind]
    if extra:
        raise ValueError(
            f"unknown action field(s) {sorted(extra)} "
            f"(timeout / only_once / async belong to the rule, not the action)"
        )

    if kind == "shell":
        return ShellAction(command=str(raw["command"]))
    if kind == "prompt":
        return PromptAction(text=str(raw["text"]))
    if kind == "http":
        headers = raw.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("http 'headers' must be a mapping")
        method = raw.get("method") or "POST"
        return HttpAction(
            url=str(raw["url"]),
            method=str(method),
            headers={str(k): str(v) for k, v in headers.items()} if headers else None,
            body=None if raw.get("body") is None else str(raw["body"]),
        )
    return SubagentAction(agent_name=str(raw["agent_name"]), prompt=str(raw["prompt"]))


# ---- 单条规则 ----


def compile_rule(raw: object, source: str, index: int = 0) -> Rule | None:
    """一条 YAML 规则 → Rule；任何校验失败都报 stderr 并返回 None。"""
    label = ""
    if isinstance(raw, dict):
        label = str(raw.get("name") or f"#{index}")
    else:
        _skip(f"#{index}", "rule must be a mapping")
        return None

    try:
        if not isinstance(raw, dict):
            raise ValueError("rule must be a mapping")
        name = raw.get("name")
        if not name or not str(name).strip():
            raise ValueError("'name' is required")
        name = str(name)

        event_raw = raw.get("event")
        event: Event | None = parse_event(str(event_raw)) if event_raw else None
        if event is None:
            _skip(name, f'unknown event "{event_raw}"')
            return None

        action = _compile_action(raw.get("action"))
        condition = _compile_condition(raw.get("if"))

        asyncio_mode = bool(raw.get("async", False))
        if asyncio_mode and is_blocking(event):
            _skip(name, "async not allowed for blocking events")
            return None

        timeout = DEFAULT_TIMEOUT
        if raw.get("timeout") is not None:
            timeout = parse_duration(raw["timeout"])
    except ValueError as exc:
        _skip(label or "?", str(exc))
        return None
    except Exception as exc:  # noqa: BLE001 —— re.error 等一并转成加载错误
        _skip(label or "?", f"invalid match: {exc}")
        return None

    return Rule(
        name=name,
        event=event,
        action=action,
        condition=condition,
        only_once=bool(raw.get("only_once", False)),
        asyncio_mode=asyncio_mode,
        timeout=timeout,
        source=source,
    )


# ---- 文件 ----


def _load_file(path: Path, seen: set[str], rules: list[Rule], sources: list[str]) -> None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _warn(f"cannot read {path}: {exc}")
        return
    except yaml.YAMLError as exc:
        _warn(f"hooks config {path} parse failed: {exc}")
        return

    if raw is None:
        return  # 空文件不算错
    if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list):
        _warn(f"hooks config {path} must be a mapping with a 'hooks' list")
        return

    sources.append(str(path))
    for i, item in enumerate(raw["hooks"]):
        rule = compile_rule(item, str(path), i)
        if rule is None:
            continue
        if rule.name in seen:
            _skip(rule.name, f"duplicate name (already loaded from {seen})")
            continue
        seen.add(rule.name)
        rules.append(rule)


def load(project_root: str | Path) -> Engine:
    """加载两层 hooks.yaml；两层都不存在时返回空 Engine（F6）。"""
    rules: list[Rule] = []
    sources: list[str] = []
    seen: set[str] = set()

    candidates = [Path(project_root) / ".mewcode" / "hooks.yaml"]
    try:
        candidates.append(Path.home() / ".mewcode" / "hooks.yaml")
    except (RuntimeError, OSError):  # home 不可解析时只用项目级
        pass

    for path in candidates:
        if path.is_file():
            _load_file(path, seen, rules, sources)
    return Engine(rules, sources)
