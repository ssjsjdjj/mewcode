"""记忆子包测试（docs/ch09 T11）：Store CRUD、索引合并/截断、异步更新。

ch10 T0a：新增 Manager.list_files 覆盖（目录缺失 / 仅 MEMORY.md / 多 .md / 混合）。
"""

from __future__ import annotations

from pathlib import Path

from mewcode.llm import Message, StreamEvent
from mewcode.memory import Manager
from mewcode.memory.store import Store
from mewcode.memory.types import UpdateAction


def _create_note(store: Store, type_: str, slug: str, title: str, content: str) -> None:
    store.apply(
        [
            UpdateAction(
                action="create",
                level="project",
                type=type_,
                title=title,
                slug=slug,
                content=content,
            )
        ]
    )


def test_store_create_note(tmp_path):
    """apply create → 文件存在、frontmatter 正确、MEMORY.md 有对应行。"""
    store = Store(str(tmp_path))
    _create_note(store, "project_knowledge", "build-command", "构建命令", "使用 pytest 运行测试。")

    note_file = tmp_path / "project_knowledge_build-command.md"
    assert note_file.is_file()
    text = note_file.read_text(encoding="utf-8")
    assert "type: project_knowledge" in text
    assert "title: 构建命令" in text
    assert "slug: build-command" in text
    assert "使用 pytest 运行测试。" in text

    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [构建命令](project_knowledge_build-command.md)" in index


def test_store_update_note(tmp_path):
    """apply update → 文件内容更新、MEMORY.md 对应行更新。"""
    store = Store(str(tmp_path))
    _create_note(store, "project_knowledge", "build-command", "构建命令", "旧内容")
    store.apply(
        [
            UpdateAction(
                action="update",
                level="project",
                filename="project_knowledge_build-command.md",
                title="构建命令",
                content="新内容",
            )
        ]
    )

    text = (tmp_path / "project_knowledge_build-command.md").read_text(encoding="utf-8")
    assert "新内容" in text
    assert "旧内容" not in text
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "新内容" in index  # 索引 hook 随内容更新
    assert index.count("project_knowledge_build-command.md") == 1  # 不产生重复行


def test_store_delete_note(tmp_path):
    """apply delete → 文件不存在、MEMORY.md 对应行消失。"""
    store = Store(str(tmp_path))
    _create_note(store, "project_knowledge", "temp", "临时", "临时内容")
    store.apply(
        [UpdateAction(action="delete", level="project", filename="project_knowledge_temp.md")]
    )

    assert not (tmp_path / "project_knowledge_temp.md").exists()
    assert "project_knowledge_temp.md" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_manager_list_files(tmp_path):
    """两级目录含 .md 与非 .md 混合 → 各按字典序返回 .md 文件名，子目录不展开。"""
    project_dir = tmp_path / "proj"
    user_dir = tmp_path / "user"
    project_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (project_dir / "note_b.md").write_text("b", encoding="utf-8")
    (project_dir / "MEMORY.md").write_text("# idx", encoding="utf-8")
    (project_dir / "note_a.md").write_text("a", encoding="utf-8")
    (project_dir / "readme.txt").write_text("x", encoding="utf-8")
    (project_dir / "sub").mkdir()
    (project_dir / "sub" / "nested.md").write_text("n", encoding="utf-8")
    (user_dir / "MEMORY.md").write_text("# u", encoding="utf-8")
    (user_dir / "pref.md").write_text("p", encoding="utf-8")
    (user_dir / "ignore.py").write_text("i", encoding="utf-8")

    mgr = Manager(str(project_dir), str(user_dir), provider=None, model="")
    project, user = mgr.list_files()
    assert project == ["MEMORY.md", "note_a.md", "note_b.md"]  # 字典序、排除非 .md 与子目录
    assert user == ["MEMORY.md", "pref.md"]


def test_manager_list_files_dir_missing(tmp_path):
    """目录不存在 → 两级均为空列表，不抛异常。"""
    mgr = Manager(str(tmp_path / "nope-proj"), str(tmp_path / "nope-user"), provider=None, model="")
    project, user = mgr.list_files()
    assert project == [] and user == []


def test_manager_list_files_only_memory(tmp_path):
    """目录仅含 MEMORY.md → 返回仅该文件。"""
    project_dir = tmp_path / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "MEMORY.md").write_text("# idx", encoding="utf-8")

    mgr = Manager(str(project_dir), str(tmp_path / "empty-user"), provider=None, model="")
    project, user = mgr.list_files()
    assert project == ["MEMORY.md"]
    assert user == []


def test_manager_list_files_oserror_degrades(tmp_path, monkeypatch):
    """OSError → logging.warning + 空列表，不抛异常。"""
    project_dir = tmp_path / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "MEMORY.md").write_text("# idx", encoding="utf-8")
    import mewcode.memory.manager as manager_mod

    monkeypatch.setattr(manager_mod.logger, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        Path,
        "glob",
        lambda self, pat: (_ for _ in ()).throw(OSError("permission denied")),
    )
    mgr = Manager(str(project_dir), str(tmp_path / "user"), provider=None, model="")
    project, user = mgr.list_files()
    assert project == [] and user == []


def test_manager_load_index(tmp_path):
    """两级各有索引 → 合并返回，项目级在前。"""
    project_dir = tmp_path / "proj"
    user_dir = tmp_path / "user"
    _create_note(
        Store(str(project_dir)), "project_knowledge", "proj-note", "项目知识", "项目级内容"
    )
    _create_note(Store(str(user_dir)), "user_preference", "user-note", "用户偏好", "用户级内容")

    mgr = Manager(str(project_dir), str(user_dir), provider=None, model="")
    index = mgr.load_index()
    assert index.index("项目知识") < index.index("用户偏好")  # 项目级在前
    assert "项目级内容" in index and "用户级内容" in index


def test_manager_load_index_truncate(tmp_path):
    """索引超过 25KB → 截断 + (index truncated) 标注。"""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    # 直接构造超大的 MEMORY.md（hook 截断让单条笔记到不了 25KB，需要真实大索引）
    (project_dir / "MEMORY.md").write_text(
        "- [条目](" + "x" * (26 * 1024) + ") — hook\n", encoding="utf-8"
    )

    mgr = Manager(str(project_dir), str(tmp_path / "user"), provider=None, model="")
    index = mgr.load_index()
    assert "(index truncated)" in index
    assert len(index.encode("utf-8")) <= 25 * 1024


class _FakeProvider:
    """返回固定文本的假 provider，用于验证 update_async 的解析与分发。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.name = "fake"
        self.model = "fake-model"

    async def stream(self, req):
        yield StreamEvent(text=self._text)
        yield StreamEvent(done=True)


async def test_manager_update_async_parses_response(tmp_path):
    """mock provider 返回 JSON → 笔记文件被创建。"""
    project_dir = tmp_path / "proj"
    user_dir = tmp_path / "user"
    fake = _FakeProvider(
        '[{"action": "create", "level": "project", "type": "project_knowledge", '
        '"title": "命令", "slug": "cmd", "content": "用 pytest 测试"}]'
    )
    mgr = Manager(str(project_dir), str(user_dir), provider=fake, model="fake")
    await mgr.update_async([Message(role="user", content="记得用 pytest")])

    assert (project_dir / "project_knowledge_cmd.md").is_file()
    assert "命令" in (project_dir / "project_knowledge_cmd.md").read_text(encoding="utf-8")
    # 未指定 level 的操作应保持 project 级，不会跑到 user 级
    assert not (user_dir / "project_knowledge_cmd.md").exists()
