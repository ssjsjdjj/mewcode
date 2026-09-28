"""危险命令黑名单（docs/ch06 T2 / F1）。

启发式防御、非完备、**不可配置放开**（N1）——bypassPermissions 模式也拦得住。
用户不可增删或关闭本黑名单。
"""

from __future__ import annotations

import re

_BLACKLIST: list[re.Pattern] = [
    # 递归强删根 / 家目录
    re.compile(r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\$HOME|/\*)"),
    # 写块设备
    re.compile(r"dd\s+.*of=/\s*dev/"),
    re.compile(r"\bdd\s+.*of=/dev/(sd|hd|nvme|disk)"),
    # fork bomb
    re.compile(r":\(\)\s*\{\s*:.*\|.*&\s*\}\s*;"),
    # 格式化文件系统
    re.compile(r"\bmkfs\."),
    # 重定向覆盖磁盘设备
    re.compile(r">\s*/dev/(sd|hd|nvme|disk)"),
    # 递归全权 chmod 根目录
    re.compile(r"chmod\s+-R\s+0?777\s+(/|/\*)"),
]


def hits_blacklist(command: str) -> bool:
    """命令串命中任一高危正则即返回 True。"""
    return any(pattern.search(command) for pattern in _BLACKLIST)
