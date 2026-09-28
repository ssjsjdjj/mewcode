"""tool 包单测（docs/ch03 T9）：注册中心 + 六工具。"""

import json

import mewcode.tool.bash as bash_mod
from mewcode.tool import new_default_registry


def j(d: dict) -> str:
    return json.dumps(d)


async def collect(registry, name, args, timeout=30.0):
    return await registry.execute(name, args, timeout)


# ---------- 注册中心 ----------


def test_registry_definitions_and_lookup():
    r = new_default_registry()
    defs = r.definitions()
    assert [d.name for d in defs] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert r.get("read_file") is not None
    assert r.get("nope") is None
    for d in defs:
        assert d.input_schema["type"] == "object"
        assert "required" in d.input_schema


def test_registry_count():
    """count() = 已注册工具数量（docs/ch10 T0c，/status 数据源）。"""
    from mewcode.tool import Registry

    r = Registry()
    assert r.count() == 0
    r.register(new_default_registry().get("read_file"))
    assert r.count() == 1


def test_register_duplicate_raises():
    from mewcode.tool import Registry

    r = Registry()

    class T:
        def name(self):
            return "x"

        def description(self):
            return "d"

        def parameters(self):
            return {}

        async def execute(self, args):
            from mewcode.tool import Result

            return Result("ok")

    r.register(T())
    try:
        r.register(T())
        assert False, "应抛 ValueError"
    except ValueError:
        pass


# ---------- read_file ----------


async def test_read_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("hello\nworld\n", encoding="utf-8")
    r = new_default_registry()
    res = await collect(r, "read_file", j({"path": str(f)}))
    assert not res.is_error
    assert "hello" in res.content and "world" in res.content


async def test_read_file_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = new_default_registry()
    res = await collect(r, "read_file", '{"path": "no-such-file.txt"}')
    assert res.is_error
    assert "不存在" in res.content


# ---------- write_file ----------


async def test_write_file_nested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = new_default_registry()
    res = await collect(r, "write_file", '{"path": "a/b/c.txt", "content": "hi"}')
    assert not res.is_error
    assert (tmp_path / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "hi"


# ---------- edit_file ----------


async def test_edit_file_unique(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "e.txt"
    f.write_text("aaa bbb aaa", encoding="utf-8")
    r = new_default_registry()
    res = await collect(
        r, "edit_file", '{"path": "e.txt", "old_string": "bbb", "new_string": "BBB"}'
    )
    assert not res.is_error
    assert f.read_text(encoding="utf-8") == "aaa BBB aaa"


async def test_edit_file_zero_and_multi(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "e.txt"
    f.write_text("aaa aaa", encoding="utf-8")
    r = new_default_registry()
    zero = await collect(
        r, "edit_file", '{"path": "e.txt", "old_string": "zzz", "new_string": "x"}'
    )
    assert zero.is_error and "未找到" in zero.content
    multi = await collect(
        r, "edit_file", '{"path": "e.txt", "old_string": "aaa", "new_string": "x"}'
    )
    assert multi.is_error and "不唯一" in multi.content and "2" in multi.content


# ---------- bash ----------


async def test_bash_echo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = new_default_registry()
    res = await collect(r, "bash", '{"command": "echo hi"}')
    assert not res.is_error
    assert "hi" in res.content and "exit_code: 0" in res.content


async def test_bash_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = bash_mod.BASH_TIMEOUT
    bash_mod.BASH_TIMEOUT = 0.2
    try:
        r = new_default_registry()
        res = await collect(r, "bash", '{"command": "sleep 5"}')
        assert res.is_error and "超时" in res.content
    finally:
        bash_mod.BASH_TIMEOUT = old


# ---------- glob / grep ----------


async def test_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x", encoding="utf-8")
    r = new_default_registry()
    res = await collect(r, "glob", '{"pattern": "**/*.py"}')
    assert not res.is_error
    assert "a.py" in res.content and "b.py" in res.content


async def test_grep_hit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello world\nfoo bar\n", encoding="utf-8")
    r = new_default_registry()
    res = await collect(r, "grep", '{"pattern": "hello"}')
    assert not res.is_error
    assert "a.txt:1:hello world" in res.content


async def test_grep_bad_regex(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = new_default_registry()
    res = await collect(r, "grep", '{"pattern": "("}')
    assert res.is_error and "正则" in res.content


# ---------- 未知工具 ----------


async def test_unknown_tool():
    r = new_default_registry()
    res = await collect(r, "nope", "{}")
    assert res.is_error and "未知工具" in res.content
