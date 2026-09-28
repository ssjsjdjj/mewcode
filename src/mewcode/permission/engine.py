"""权限引擎：前四层判定流水线 + 配置加载（docs/ch06 T6 / F4/F6）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mewcode.llm import ToolCall

from . import Category, Decision, Mode, parse_mode
from .blacklist import hits_blacklist
from .rule import RuleSet
from .sandbox import resolve_root, sandbox_ok
from .settings import (
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)

_CATEGORY_LABEL = {
    Category.READ: "只读",
    Category.WRITE: "文件写",
    Category.EXEC: "命令执行",
}


@dataclass
class Engine:
    root: str
    blacklist: list  # 内置危险命令正则（不可配，N1）
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: str = ""
    start_mode: Mode = Mode.DEFAULT

    def check(self, mode: Mode, call: ToolCall, read_only: bool) -> tuple[Decision, str]:
        """前四层判定（短路）：黑名单 → 沙箱 → 规则 → 模式兜底。Ask 表示请走第五层。"""
        cat = categorize(call.name, read_only)
        friendly = friendly_name(call.name)
        target, is_file, ok = extract_target(call)

        # ① 黑名单（仅 Exec 类，且 target 非空）——N1 最高优先，bypass 也拦
        if cat == Category.EXEC and target and hits_blacklist(target):
            return Decision.DENY, f"命中危险命令黑名单：{target[:60]}"

        # ② 沙箱（仅文件类）
        if is_file:
            if not ok:
                return Decision.DENY, "无法解析文件路径参数，安全拒绝"
            if not sandbox_ok(self, target):
                return Decision.DENY, f"路径在项目目录之外：{target[:60]}"

        # ③ 规则引擎：本地 > 项目 > 用户，就近命中即返回
        for level, rs in (("本地", self.local), ("项目", self.project), ("用户", self.user)):
            decision, hit = rs.match(friendly, target)
            if hit:
                return decision, f"{level}级规则：{friendly}({target[:60]})"

        # ④ 模式兜底（只产 Allow/Ask）
        decision = mode_fallback(mode, cat)
        if decision == Decision.ASK:
            return decision, f"{mode} 模式下{_CATEGORY_LABEL[cat]}类操作需确认"
        return decision, ""

    def persist_local_allow(self, call: ToolCall) -> None:
        from .persist import persist_local_allow

        persist_local_allow(self, call)


def mode_fallback(mode: Mode, cat: Category) -> Decision:
    """F5 模式矩阵：只产 Allow/Ask。"""
    if cat == Category.READ or mode == Mode.BYPASS:
        return Decision.ALLOW
    if mode == Mode.ACCEPT_EDITS and cat == Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def _load_rule_set(path: str) -> RuleSet:
    """加载单个配置文件为规则集；缺失/格式非法降级为空（N5）。"""
    try:
        return to_rule_set(load_settings(path))
    except SettingsError:
        return RuleSet()


def new_engine(root: str) -> tuple[Engine, Exception | None]:
    """构造引擎。唯一致命 err 是项目根不可解析；此时仍返回非 None 空规则安全引擎。"""
    try:
        resolved_root = resolve_root(root)
        err = None
    except Exception as exc:  # noqa: BLE001
        resolved_root = root
        err = exc

    user = _load_rule_set(str(Path.home() / ".mewcode/settings.yaml"))
    project = _load_rule_set(str(Path(resolved_root) / ".mewcode/settings.yaml"))
    local = _load_rule_set(str(Path(resolved_root) / ".mewcode/settings.local.yaml"))

    # 启动默认模式：本地 > 项目 > 用户
    start = Mode.DEFAULT
    for path in (
        str(Path(resolved_root) / ".mewcode/settings.local.yaml"),
        str(Path(resolved_root) / ".mewcode/settings.yaml"),
        str(Path.home() / ".mewcode/settings.yaml"),
    ):
        try:
            settings = load_settings(path)
        except SettingsError:
            continue
        parsed, ok = parse_mode(settings.default_mode)
        if ok:
            start = parsed
            break

    from .blacklist import _BLACKLIST

    engine = Engine(
        root=resolved_root,
        blacklist=_BLACKLIST,
        user=user,
        project=project,
        local=local,
        local_path=str(Path(resolved_root) / ".mewcode/settings.local.yaml"),
        start_mode=start,
    )
    return engine, err


# 兼容纯函数式调用（plan 允许方法或函数两形态）
def check(engine: Engine, mode: Mode, call: ToolCall, read_only: bool) -> tuple[Decision, str]:
    return engine.check(mode, call, read_only)


def start_mode(engine: Engine) -> Mode:
    return engine.start_mode()


def persist_local_allow(engine: Engine, call: ToolCall) -> None:
    from .persist import persist_local_allow as _impl

    _impl(engine, call)
