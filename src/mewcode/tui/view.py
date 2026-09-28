"""渲染拼装：用户块、markdown 定型、错误、状态栏、工具行（ch03）。"""

from __future__ import annotations

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.text import Text


def user_block(text: str) -> Text:
    """用户消息块（无文字标签，Claude Code 风格）。"""
    return Text(text)


def notice_block(text: str) -> Text:
    """系统提示块（灰字，仅 scrollback，不入对话历史；docs/ch08 T33）。"""
    return Text(text, style="dim")


def render_markdown(reply: str) -> RenderableType:
    """助手回复定型为 markdown。"""
    return Markdown(reply)


def error_block(err: Exception | str) -> Text:
    """错误块（红色可区分）。"""
    return Text(f"⚠ {err}", style="bold red")


def _fmt_tokens(n: int) -> str:
    """紧凑数字：1234 → 1.2k。"""
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


_MODE_LABELS = {
    "default": ("DEFAULT", "dim"),
    "acceptEdits": ("ACCEPT EDITS", "green"),
    "plan": ("PLAN", "yellow"),
    "bypassPermissions": ("BYPASS", "bold red"),
}


def status_text(
    model: str,
    *,
    usage_in: int = 0,
    usage_out: int = 0,
    mode=None,
) -> Text:
    """状态栏：左常驻权限模式（取代 provider 名），右模型名 + 累计用量。"""
    if mode is not None:
        label, style = _MODE_LABELS.get(str(mode), ("DEFAULT", "dim"))
        mode_part = Text(f"{label}", style=style)
    else:
        mode_part = Text("")
    usage = ""
    if usage_in or usage_out:
        usage = f"  ↑{_fmt_tokens(usage_in)} ↓{_fmt_tokens(usage_out)} tok"
    return Text.assemble(mode_part, Text(f"  ·  {model}{usage}"))


def approval_block(req, cursor: int) -> Text:
    """人在回路多行待批准块（docs/ch06 F8）。"""
    lines: list[Text] = [
        Text(f"● {req.name}", style="bold cyan"),
        Text(f"  {req.args}", style="dim"),
        Text(f"  {req.reason}", style="dim"),
        Text("  是否继续？"),
    ]
    options = [
        "1. 允许本次",
        "2. 永久允许（写入本地配置）",
        "3. 拒绝本次",
    ]
    for idx, label in enumerate(options):
        if idx == cursor:
            lines.append(Text(f"> {label}", style="bold yellow"))
        else:
            lines.append(Text(f"  {label}"))
    lines.append(Text("↑↓ 选择 · 回车确认 · Esc 取消", style="dim"))
    return Text("\n".join(str(t) for t in lines))


def tool_line(name: str, args: str) -> Text:
    """工具行：`● name(args)`（ch03 F8）。"""
    return Text.assemble(Text("● ", style="bold cyan"), Text(f"{name}({args})", style="bold"))


def tool_result_summary(result: str, is_error: bool) -> RenderableType:
    """工具结果摘要（缩进、灰/红、UI 截断 ~8 行）。"""
    lines = result.splitlines()
    if len(lines) > 8:
        lines = lines[:8] + ["…(截断)"]
    summary = "\n".join(lines)
    style = "bold red" if is_error else "dim"
    return Padding(Text(f"⎿ {summary}", style=style), (0, 0, 0, 2))
