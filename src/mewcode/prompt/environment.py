"""环境信息采集与渲染（docs/ch05 T2）。"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from dataclasses import dataclass

_GIT_TIMEOUT = 2.0
_GIT_HEAD_LIMIT = 3


@dataclass
class Environment:
    working_dir: str
    platform: str
    date: str
    git_status: str
    version: str
    model: str

    def render(self) -> str:
        """渲染为「环境信息」段：逐行 Key: Value，空值项省略。"""
        lines = [
            ("Working directory", self.working_dir),
            ("Platform", self.platform),
            ("Date", self.date),
            ("Git status", self.git_status),
            ("MewCode version", self.version),
            ("Model", self.model),
        ]
        parts = [f"{key}: {value}" for key, value in lines if value]
        return "Environment:\n" + "\n".join(parts)


def _git_status() -> str:
    """采集 git 状态摘要；非 git 目录 / git 不可用 / 超时 / 解码失败均降级为空串。"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # 避免中文 Windows 上 GBK 解码抛异常
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
        return ""
    if result.returncode != 0:
        return ""
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return "clean"
    summary = f"{len(lines)} file(s) changed"
    head = "\n".join(lines[:_GIT_HEAD_LIMIT])
    return f"{summary}\n{head}"


def gather_environment(version: str, model: str) -> Environment:
    """采集运行环境（不读取任何环境变量，N5）。"""
    try:
        working_dir = os.getcwd()
    except OSError:
        working_dir = ""
    return Environment(
        working_dir=working_dir,
        platform=sys.platform,
        date=datetime.date.today().isoformat(),
        git_status=_git_status(),
        version=version,
        model=model,
    )
