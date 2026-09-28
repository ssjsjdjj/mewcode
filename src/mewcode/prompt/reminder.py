"""补充消息（system-reminder）与规划模式提醒（docs/ch05 T3）。"""

from __future__ import annotations

# /do 注入的用户消息：指示模型按上文已确认的计划开始执行
EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"

_PLAN_REMINDER_FULL = (
    "You are currently in PLAN MODE. You may use ONLY the read-only tools "
    "(read_file, glob, grep) to investigate the codebase. You must NOT write files, "
    "edit files, or run shell commands. Produce a clear, step-by-step plan for the task, "
    "then stop and wait for the user to approve it with /do before doing any work."
)

_PLAN_REMINDER_CONCISE = (
    "You are in PLAN MODE: read-only tools only; produce a plan and wait for /do."
)


def system_reminder(body: str) -> str:
    """用 <system-reminder> 标签包裹补充指令。"""
    return f"<system-reminder>\n{body}\n</system-reminder>"


def plan_reminder(full: bool) -> str:
    """规划模式提醒：full=完整版，否则精简版（docs/ch05 F7）。"""
    body = _PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE
    return system_reminder(body)
