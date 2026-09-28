"""InstallSkill 的核心逻辑：下载 zip、校验路径、解压到 `~/.mewcode/skills/`（docs/ch11 T18）。

安全要点（F31/N8）：zip 内所有条目必须位于同一个顶层目录下、该目录名符合 Skill 命名
规范、不含 `..`、不是绝对路径、不是符号链接。任一条不满足都拒绝整包，不留副作用。

解压采用「先解到临时目录、校验通过后再原子换入目标位置」，避免中途失败留下半个 Skill。
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

import httpx2

from .catalog import Catalog, user_skills_dir
from .parser import SKILL_NAME_RE

MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50MB
DOWNLOAD_TIMEOUT = 60.0
_SYMLINK_MODE = stat.S_IFLNK


class UnsafeArchiveError(ValueError):
    """zip 内含不安全路径或结构非法。"""


def _top_level_dir(names: list[str]) -> str:
    """从条目名推出唯一的顶层目录名，不唯一则报错。"""
    tops = set()
    for name in names:
        parts = Path(name).parts
        if not parts:
            continue
        tops.add(parts[0])
    if len(tops) != 1:
        raise UnsafeArchiveError(
            f"zip must contain exactly one top-level directory, found {sorted(tops)}"
        )
    return tops.pop()


def _validate_path_safe(info: zipfile.ZipInfo) -> None:
    """路径本身是否安全：不含 `..`、不是绝对路径/盘符、不是符号链接（N8）。

    先于顶层目录推断执行，这样逃逸路径报的是 `unsafe path` 而不是被
    「顶层目录不唯一」抢先。
    """
    raw = info.filename
    parts = Path(raw).parts
    if not parts:
        return
    if ".." in parts:
        raise UnsafeArchiveError(f"unsafe path in zip: {raw}")
    if Path(raw).is_absolute() or raw.startswith(("/", "\\")) or ":" in parts[0]:
        raise UnsafeArchiveError(f"unsafe path in zip: {raw}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode) or (mode & 0o170000) == _SYMLINK_MODE:
        raise UnsafeArchiveError(f"symlink not allowed in zip: {raw}")


def _validate_inside(info: zipfile.ZipInfo, top: str) -> None:
    """所有条目必须位于同一个顶层目录下。"""
    parts = Path(info.filename).parts
    if parts and parts[0] != top:
        raise UnsafeArchiveError(f"unsafe path in zip: {info.filename} (outside {top}/)")


def _extract_checked(archive: zipfile.ZipFile, target: Path) -> None:
    """校验通过后解压到 target（调用方保证 target 不存在）。"""
    archive.extractall(target)


async def _download(source: str, dest: Path) -> None:
    """流式下载 source 到 dest，超时 60s、上限 50MB。"""
    async with httpx2.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", source) as resp:
            resp.raise_for_status()
            total = 0
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_ZIP_BYTES:
                        raise UnsafeArchiveError("zip too large (>50MB)")
                    fh.write(chunk)


async def install_from_url(source: str, catalog: Catalog, work_dir: Path | str) -> str:
    """下载并安装一个 Skill 包，返回 Skill 名（顶层目录名）。

    失败时抛异常，且不改变 `~/.mewcode/skills/` 下的既有内容。
    """
    skills_root = user_skills_dir()
    with tempfile.TemporaryDirectory(prefix="mewcode-skill-") as tmp:
        tmpdir = Path(tmp)
        zip_path = tmpdir / "download.zip"
        await _download(source, zip_path)

        try:
            archive = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as exc:
            raise UnsafeArchiveError(f"not a valid zip: {exc}") from exc

        with archive:
            names = [i.filename for i in archive.infolist() if not i.is_dir()]
            if not names:
                raise UnsafeArchiveError("zip is empty")
            for info in archive.infolist():
                _validate_path_safe(info)

            top = _top_level_dir(names)
            if not SKILL_NAME_RE.match(top):
                raise UnsafeArchiveError(
                    f"invalid skill name {top!r} (want ^[a-z][a-z0-9-]*$, 1-32)"
                )
            for info in archive.infolist():
                _validate_inside(info, top)

            # 解到 tmpdir；条目自带顶层目录，产物即 tmpdir/<top>
            _extract_checked(archive, tmpdir)
            staged = tmpdir / top
            if not (staged / "SKILL.md").is_file():
                raise UnsafeArchiveError(f"zip has no {top}/SKILL.md")

            skills_root.mkdir(parents=True, exist_ok=True)
            final = skills_root / top
            if final.exists():
                shutil.rmtree(final)
            shutil.move(str(staged), str(final))

    catalog.reload(work_dir)
    return top
