"""会话恢复 UI（docs/ch09 T14/T22-F23）：RESUMING 状态、会话列表项、恢复动作。

复用 Textual `OptionList`（与 provider 选择一致）做会话列表；Enter 恢复
选中项、Esc 返回空闲态。恢复流程覆盖坏行跳过、孤立工具调用截断、时间跨度
提醒、token 超限压缩（复用 ch08 手动压缩入口）。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from textual.widgets import OptionList, RichLog

from mewcode import compact
from mewcode.compact.const import MANUAL_SAFETY_MARGIN
from mewcode.compact.token import estimate_tokens
from mewcode.conversation import Conversation
from mewcode.session import SessionInfo, Writer, load_session
from mewcode.tui import SessionState
from mewcode.tui.view import notice_block

RESUME_STALE_SECONDS = 6 * 3600  # 时间跨度提醒阈值（docs/ch09 F21）


def _relative_time(modified_at: datetime) -> str:
    """相对时间展示：刚刚 / N 分钟前 / N 小时前 / N 天前。"""
    delta = datetime.now() - modified_at
    if delta.days >= 1:
        return f"{delta.days} 天前"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours} 小时前"
    minutes = delta.seconds // 60
    if minutes >= 1:
        return f"{minutes} 分钟前"
    return "刚刚"


def _format_size(size: int) -> str:
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def _format_duration(seconds: int) -> str:
    """把秒数格式化为 'N 天 N 小时 N 分钟'（F21 提醒文案用）。"""
    days, rem = divmod(seconds, 86400)
    hours, minutes = divmod(rem, 3600)
    minutes //= 60
    parts: list[str] = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes or not parts:
        parts.append(f"{minutes} 分钟")
    return " ".join(parts)


def _last_message_ts(session_dir: str) -> float | None:
    """读 conversation.jsonl 最后一条有效消息的 ts（F21 时间判断）；失败返回 None。"""
    last_ts: float | None = None
    path = Path(session_dir) / "conversation.jsonl"
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # 坏行跳过
                if obj.get("type") == "compact":
                    continue  # 压缩标记行无消息语义
                ts = obj.get("ts")
                if isinstance(ts, (int, float)):
                    last_ts = float(ts)
    except OSError:
        return None
    return last_ts


class SessionItem:
    """包装 SessionInfo，提供展示文本（docs/ch09 F19）。"""

    def __init__(self, info: SessionInfo) -> None:
        self.info = info

    @property
    def display_text(self) -> str:
        title = self.info.title or self.info.id
        return (
            f"{title} · {_relative_time(self.info.modified_at)} · "
            f"{self.info.model or '未知模型'} · {_format_size(self.info.size)}"
        )


async def handle_resume_key(app, event) -> bool:
    """RESUMING 态按键：Enter 恢复选中项、Esc 返回 IDLE；其余返回 False 交回分发。"""
    if event.key == "escape":
        app.state = SessionState.IDLE
        return True
    if event.key == "enter":
        select = app.query_one("#select", OptionList)
        idx = select.highlighted
        if idx is not None and 0 <= idx < len(app.resume_items):
            await do_resume_session(app, app.resume_items[idx])
        app.state = SessionState.IDLE
        return True
    return False


async def do_resume_session(app, info: SessionInfo) -> None:
    """恢复指定会话：加载、时间提醒、token 超限压缩、切换会话对象（docs/ch09 F21-F23）。

    ch12 起在切换前后各分派一次 hook（docs/ch12 T20）：SessionEnd 给旧会话收尾、
    SessionResume 给新会话开场；only_once 集合随换会话清空（N5）。
    """
    log = app.query_one("#log", RichLog)
    log.write(notice_block(f"正在恢复会话 {info.id}..."))
    if getattr(app, "hook_engine", None) is not None:
        await app._dispatch_session_end()
        await app.hook_engine.reset_for_new_session()
    # 坏行跳过 + 孤立工具调用截断在 load_session 内完成（AC14/AC15）
    msgs = load_session(info.dir)
    root = str(Path(app.sessions_dir).resolve().parent.parent)  # sessions 目录 → workspace
    new_ses_ctx = compact.open_session_context(root, info.id)
    new_writer = Writer.open_existing(info.dir)
    new_conv = Conversation.from_messages(msgs, new_writer.on_append, new_writer.on_replace)

    # 时间跨度提醒（F21）：最后一条消息 ts 距当前超过 6h → 追加 user 提醒
    last_ts = _last_message_ts(info.dir)
    if last_ts is not None and time.time() - last_ts > RESUME_STALE_SECONDS:
        duration = _format_duration(int(time.time() - last_ts))
        new_conv.add_user(
            f"[系统提示] 本会话已暂停 {duration}。部分上下文可能已过时，如需最新信息请重新读取相关文件。"
        )

    # 先切 session，压缩产生的落盘落在被恢复会话目录
    app.runtime.session = new_ses_ctx
    est = estimate_tokens(0, new_conv.messages(), 0)
    if est > app.runtime.context_window - MANUAL_SAFETY_MARGIN and app.agent is not None:
        # 与 Agent 主循环同一口径（docs/ch07 追加 T15）。此处**不** reset 已发现
        # 集合：/resume 恢复的是同一进程内的会话，已拉取的工具照旧可见（F19/AC20）。
        defs = app.visible_tool_defs()
        try:
            await app.agent.run_force_compact(new_conv, defs)
        except Exception as exc:  # noqa: BLE001 —— 压缩失败降级为未压缩历史继续
            log.write(notice_block(f"恢复时压缩失败，以未压缩历史继续: {exc}"))

    # 切换会话对象（F22）：后续新消息追加到同一 JSONL
    app.conv = new_conv
    app.writer = new_writer
    app.ses_ctx = new_ses_ctx
    if getattr(app, "hook_engine", None) is not None:
        await app._dispatch_session_resume()
    log.write(notice_block(f"已恢复会话 {info.id}，共 {new_conv.length()} 条消息"))
