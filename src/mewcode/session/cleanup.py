"""会话过期清理（docs/ch09 F15）。"""

from __future__ import annotations

import datetime as _dt
import logging
import shutil
from pathlib import Path

from mewcode.compact.state import parse_session_time

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: _dt.timedelta) -> None:
    """删除创建时间距今超过 max_age 的新格式会话目录。

    只处理目录名可解析为新格式的会话；单个删除失败告警后继续，
    不中断整轮清理。
    """
    base = Path(sessions_dir)
    if not base.is_dir():
        return
    now = _dt.datetime.now()
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            created = parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式目录跳过
        if now - created > max_age:
            try:
                shutil.rmtree(child, ignore_errors=False)
            except OSError:
                logger.warning("清理过期会话失败: %s", child, exc_info=True)
