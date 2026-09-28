"""InstallSkill 安装逻辑测试（docs/ch11 T18）：zip-slip 防护、结构校验、正常安装。

不拉真实网络：用 `httpx2.MockTransport` 注入内存 zip 响应（与 tests/test_mcp_http.py 同法）。
"""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import httpx2
import pytest

from mewcode.skills import Catalog
from mewcode.skills.install import UnsafeArchiveError, install_from_url
from mewcode.tool import new_default_registry
from mewcode.tool.install_skill import InstallSkillTool

SKILL_MD = "---\nname: {name}\ndescription: 装进来的\n---\n\n正文\n"


def make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def make_symlink_zip(link_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo(link_name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "../../outside")
    return buf.getvalue()


def good_zip(name: str = "myskill") -> bytes:
    return make_zip({f"{name}/SKILL.md": SKILL_MD.format(name=name)})


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


@pytest.fixture
def serve(monkeypatch):
    """把 httpx2.AsyncClient 换成带 MockTransport 的内存客户端。

    原始类只捕获一次、只打一次 patch，`_install` 多次调用只是换掉 handler——
    否则第二次 patch 会把前一层 wrapper 再包一层，transport 被传两次。
    """
    orig = httpx2.AsyncClient
    state: dict = {}

    def _install(payload: bytes, status: int = 200):
        def handler(request):  # noqa: ARG001
            return httpx2.Response(status, content=payload)

        state["handler"] = handler
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: orig(transport=httpx2.MockTransport(state["handler"]), **kw),
        )

    return _install


async def test_install_happy_path(tmp_path, home, serve):
    serve(good_zip("myskill"))
    work = tmp_path / "work"
    catalog = Catalog.load(work)

    name = await install_from_url("http://x/myskill.zip", catalog, work)

    assert name == "myskill"
    assert (home / ".mewcode" / "skills" / "myskill" / "SKILL.md").is_file()
    assert "myskill" in catalog.names()  # reload 已生效，无需重启（F32）


async def test_install_replaces_existing(tmp_path, home, serve):
    serve(good_zip("myskill"))
    work = tmp_path / "work"
    catalog = Catalog.load(work)
    await install_from_url("http://x/a.zip", catalog, work)

    serve(make_zip({"myskill/SKILL.md": SKILL_MD.format(name="myskill") + "\n第二版\n"}))
    await install_from_url("http://x/b.zip", catalog, work)
    body = (home / ".mewcode" / "skills" / "myskill" / "SKILL.md").read_text(encoding="utf-8")
    assert "第二版" in body


async def test_install_zip_slip_rejected(tmp_path, home, serve):
    """含 ../ 的条目拒绝解压，且 skills 目录无副作用（N8/AC15）。"""
    serve(make_zip({"evil/SKILL.md": "x", "evil/../../passwd": "pwned"}))
    work = tmp_path / "work"
    catalog = Catalog.load(work)

    with pytest.raises(UnsafeArchiveError, match="unsafe path"):
        await install_from_url("http://x/evil.zip", catalog, work)
    assert not (home / ".mewcode" / "skills" / "evil").exists()


async def test_install_absolute_path_rejected(tmp_path, home, serve):
    serve(make_zip({"evil/SKILL.md": "x", "/tmp/absolute": "pwned"}))
    with pytest.raises(UnsafeArchiveError, match="unsafe path"):
        await install_from_url("http://x/evil.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_symlink_rejected(tmp_path, home, serve):
    serve(make_symlink_zip("evil/link"))
    with pytest.raises(UnsafeArchiveError, match="symlink"):
        await install_from_url("http://x/evil.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_two_top_dirs_rejected(tmp_path, home, serve):
    serve(make_zip({"a/SKILL.md": "x", "b/SKILL.md": "y"}))
    with pytest.raises(UnsafeArchiveError, match="exactly one top-level"):
        await install_from_url("http://x/two.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_bad_top_name_rejected(tmp_path, home, serve):
    serve(make_zip({"Bad_Name/SKILL.md": "x"}))
    with pytest.raises(UnsafeArchiveError, match="invalid skill name"):
        await install_from_url("http://x/bad.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_missing_skill_md_rejected(tmp_path, home, serve):
    serve(make_zip({"myskill/README.md": "x"}))
    with pytest.raises(UnsafeArchiveError, match=r"no myskill/SKILL.md"):
        await install_from_url("http://x/noskill.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_not_a_zip(tmp_path, home, serve):
    serve(b"this is not a zip")
    with pytest.raises(UnsafeArchiveError, match="not a valid zip"):
        await install_from_url("http://x/x.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_http_error(tmp_path, home, serve):
    serve(b"nope", status=404)
    with pytest.raises(httpx2.HTTPStatusError):
        await install_from_url("http://x/x.zip", Catalog.load(tmp_path / "w"), tmp_path / "w")


async def test_install_skill_tool_wraps_result(tmp_path, home, serve):
    serve(good_zip("myskill"))
    work = tmp_path / "work"
    tool = InstallSkillTool(Catalog.load(work), work)
    assert tool.name() == "install_skill"
    assert tool.read_only is False  # 有副作用，必须走权限授权（F33）
    assert tool.is_system is False

    r = await tool.execute('{"source": "http://x/myskill.zip"}')
    assert r.is_error is False
    assert "installed to ~/.mewcode/skills/myskill" in r.content


async def test_install_skill_tool_reports_failure(tmp_path, home, serve):
    serve(make_zip({"evil/SKILL.md": "x", "evil/../x": "y"}))
    work = tmp_path / "work"
    tool = InstallSkillTool(Catalog.load(work), work)
    r = await tool.execute('{"source": "http://x/evil.zip"}')
    assert r.is_error is True
    assert "安装 Skill 失败" in r.content


async def test_install_skill_tool_arg_validation(tmp_path, home):
    tool = InstallSkillTool(Catalog.load(tmp_path / "w"), tmp_path / "w")
    r = await tool.execute("{}")
    assert r.is_error is True and "source" in r.content
    r = await tool.execute("{bad")
    assert r.is_error is True and "JSON" in r.content


def test_install_tool_is_a_tool():
    from mewcode.tool import Tool

    assert isinstance(InstallSkillTool(Catalog(), "."), Tool)
    assert new_default_registry().get("install_skill") is None  # 不是默认工具，由 cli 注册
