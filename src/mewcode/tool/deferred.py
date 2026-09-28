"""延迟加载视图（docs/ch07 追加 F13–F20）。

MCP 工具的完整 schema 默认不进请求：本轮只注入「不可延迟」+「已发现」的工具，
其余工具的**名字**写进 system-reminder 清单，模型需要时用 tool_search 拉取。

本模块对 MCP 完全无知——它只看到「有些工具的 `deferrable` 是 True」；不写文件、
不发网络、不依赖 permission 包（因此可见性参数用布尔而非 `Mode`）。已发现集合是
纯会话内存态：进程重启即空，不落盘（F19）。
"""

from __future__ import annotations

import json

from mewcode.llm import ToolDefinition
from mewcode.tool import Registry, Result

# 搜索一次最多返回多少条（F18；精确拉取与名字清单不设上限）
SEARCH_LIMIT = 5

# 名字不符合 mcp__<server>__<tool> 形状的可延迟工具归入该分组（分组只影响清单排版）
_OTHER_GROUP = "其他"

MANIFEST_HEAD = "以下 MCP 工具尚未加载完整定义，需要时用 tool_search 获取："
MANIFEST_USAGE = "- select:<完整工具名>  精确拉取\n- 关键词               模糊搜索（最多返回 5 个）"


def _server_of(full_name: str) -> str:
    """从 mcp__<server>__<tool> 取 <server>；形状不符则归入「其他」。

    按第一个 `__` 切分 server 与工具名（工具名自身可能含 `__`），与适配层
    `f"mcp__{server_name}__{t.name}"` 的拼法对称。
    """
    head, sep, rest = full_name.partition("__")
    if head != "mcp" or not sep:
        return _OTHER_GROUP
    server, sep2, _tool = rest.partition("__")
    return server if sep2 else _OTHER_GROUP


class Discovery:
    """会话级的「哪些工具本轮可见」视图；拉取与搜索的状态变更都在这里。

    只用 Registry 的公开只读接口（`definitions` / `read_only_definitions` / `get` /
    `is_deferrable` / `deferrable_names` / `has_deferrable`），不触其内部字段。
    """

    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._found: set[str] = set()

    # ---- 只读查询 ----

    def has_deferrable(self) -> bool:
        """是否存在可延迟工具（cli 据此决定是否注册 tool_search，F16）。"""
        return self._registry.has_deferrable()

    def deferred_names(self) -> list[str]:
        """可延迟**且尚未拉取**的工具名，按注册顺序（F14/F15）。"""
        return [n for n in self._registry.deferrable_names() if n not in self._found]

    def discovered_names(self) -> list[str]:
        """已拉取的工具名，按注册顺序（供 UI / 测试观察会话内存态）。"""
        return [n for n in self._registry.deferrable_names() if n in self._found]

    def visible_definitions(self, plan_only: bool) -> list[ToolDefinition]:
        """本轮应注入的完整定义（F14/F22）。

        = 按模式过滤后的全集，再滤掉「可延迟且尚未拉取」的；相对顺序 = 注册顺序。
        无可延迟工具时是对全集的恒等变换（F23 的字节级不变就靠这条）。
        """
        defs = self._registry.read_only_definitions() if plan_only else self._registry.definitions()
        return [
            d
            for d in defs
            if not (self._registry.is_deferrable(d.name) and d.name not in self._found)
        ]

    def manifest(self) -> str | None:
        """名字清单正文；无「可延迟且未拉取」的工具时返回 None（调用方完全不追加）。

        只含名字（省 token 的来源），按 server 分组、组间与组内均排序（N11 确定性）。
        **不设条数上限**：截断会让被截掉的工具永久不可达（F15）。
        """
        names = self.deferred_names()
        if not names:
            return None
        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(_server_of(name), []).append(name)
        lines = [MANIFEST_HEAD, MANIFEST_USAGE, ""]
        for server in sorted(groups):
            lines.append(f"[{server}]")
            lines.extend(f"- {name}" for name in sorted(groups[server]))
        return "\n".join(lines)

    # ---- 动作（供 tool_search 调用；一律返回文本，从不抛异常） ----

    def select(self, name: str) -> Result:
        """精确拉取（F17）：命中则标记已发现并返回完整定义；未命中返回错误结果。

        返回 `Result` 而非裸字符串：「没找到」是失败结果，交给上层当结构化错误回灌
        （字符串则要靠内容嗅探判成败）。
        """
        name = name.strip()
        if not name:
            return Result(
                content="用法错误：select: 后需要完整的工具名，"
                "例如 select:mcp__filesystem__read_file。",
                is_error=True,
            )
        tool = self._registry.get(name)
        if tool is None:
            return Result(
                content=f"没有名为 {name} 的工具。可用 tool_search 按关键词搜索，或参考名字清单。",
                is_error=True,
            )
        if self._registry.is_deferrable(name):
            self._found.add(name)
        params = json.dumps(tool.parameters(), ensure_ascii=False, sort_keys=True)
        return Result(
            content=(
                f"已加载 {name}，从下一轮起进入工具列表。\n"
                f"描述：{tool.description()}\n"
                f"参数 schema：{params}"
            )
        )

    def search(self, keyword: str) -> Result:
        """关键词搜索（F18）：名字命中优先于描述命中，同级按注册顺序，最多 5 条。"""
        keyword = keyword.strip()
        if not keyword:
            return Result(
                content="用法错误：请给出搜索关键词，或用 select:<完整工具名> 精确拉取。",
                is_error=True,
            )
        kw = keyword.lower()
        name_hits: list[str] = []
        desc_hits: list[str] = []
        for name in self._registry.deferrable_names():
            tool = self._registry.get(name)
            if tool is None:  # 已在 deferrable_names 中出现，理论上不可能
                continue
            if kw in name.lower():
                name_hits.append(name)
            elif kw in tool.description().lower():
                desc_hits.append(name)
        hits = name_hits + desc_hits  # 名字命中整体优先；同级保持注册顺序
        if not hits:
            return Result(
                content=f"没有匹配「{keyword}」的工具。可换更宽的关键词重试，或参考名字清单。",
                is_error=True,
            )
        shown = hits[:SEARCH_LIMIT]
        for name in shown:
            self._found.add(name)
        lines = [f"匹配「{keyword}」的工具（已加载，从下一轮起进入工具列表；最多 5 条）："]
        for name in shown:
            tool = self._registry.get(name)
            desc = tool.description() if tool is not None else ""
            lines.append(f"- {name}：{desc}")
        if len(hits) > SEARCH_LIMIT:
            lines.append(f"（已截断，共 {len(hits)} 个匹配；可换更精确的关键词。）")
        return Result(content="\n".join(lines))

    def reset(self) -> None:
        """清空已发现集合（`/clear` 开新会话用）；不触及注册中心。"""
        self._found.clear()
