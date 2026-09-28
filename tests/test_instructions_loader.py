"""项目指令加载器测试（docs/ch09 T3）。"""

from __future__ import annotations

from pathlib import Path

from mewcode.instructions import Loader


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_three_layer_priority(tmp_path, monkeypatch):
    """项目根最前，其次 .mewcode/，最后用户级。"""
    _write(tmp_path / "MEWCODE.md", "项目根指令")
    _write(tmp_path / ".mewcode" / "MEWCODE.md", "项目配置指令")
    user = tmp_path / "home"
    _write(user / ".mewcode" / "MEWCODE.md", "用户指令")
    loader = Loader(str(tmp_path), user_home=str(user))
    out = loader.load()
    assert out.index("项目根指令") < out.index("项目配置指令") < out.index("用户指令")


def test_missing_files_silent(tmp_path, monkeypatch):
    """三层全空：返回空串。只放项目根：只含其内容。"""
    loader = Loader(str(tmp_path), user_home=str(tmp_path / "home"))
    assert loader.load() == ""
    _write(tmp_path / "MEWCODE.md", "只有项目根")
    assert loader.load() == "只有项目根"


def test_include_expands(tmp_path):
    _write(tmp_path / "MEWCODE.md", "@include rules/style.md")
    _write(tmp_path / "rules" / "style.md", "代码块必须带语言标记")
    out = Loader(str(tmp_path)).load()
    assert "代码块必须带语言标记" in out
    assert "@include" not in out


def test_include_nested(tmp_path):
    """A include B，B include C → A 输出含 C 内容。"""
    _write(tmp_path / "MEWCODE.md", "@include b.md")
    _write(tmp_path / "b.md", "B 开头\n@include c.md")
    _write(tmp_path / "c.md", "C 内容")
    out = Loader(str(tmp_path)).load()
    assert "B 开头" in out and "C 内容" in out


def test_include_depth_limit(tmp_path):
    """层数：MEWCODE.md=1，其 include 的文件=2 … 第 6 层不展开，出现深度警告注释。"""
    for i in range(1, 7):
        _write(tmp_path / f"f{i}.md", f"@include f{i + 1}.md\n内容{i}")
    # MEWCODE.md(1) → f1(2) → f2(3) → f3(4) → f4(5，允许) → f5(6，跳过)
    _write(tmp_path / "MEWCODE.md", "@include f1.md")
    out = Loader(str(tmp_path), max_depth=5).load()
    for i in range(1, 5):
        assert f"内容{i}" in out
    assert "内容5" not in out  # f5 是第 6 层
    assert "超过最大嵌套深度" in out


def test_include_loop_detected(tmp_path):
    """A include B，B include A → 第二次引用不展开，出现环路警告。"""
    _write(tmp_path / "a.md", "@include b.md\nA正文")
    _write(tmp_path / "b.md", "@include a.md\nB正文")
    _write(tmp_path / "MEWCODE.md", "@include a.md")
    out = Loader(str(tmp_path)).load()
    assert "检测到环路" in out
    assert "A正文" in out and "B正文" in out


def test_include_escape_rejected(tmp_path):
    """项目级 MEWCODE.md @include 跳出项目根 → 范围警告，不加载。"""
    outside = tmp_path / "outside" / "secret.md"
    _write(outside, "外部机密")
    # 用 .. 逃逸到项目根之外
    _write(tmp_path / "MEWCODE.md", "@include ../outside/secret.md")
    out = Loader(str(tmp_path)).load()
    assert "路径超出允许范围" in out
    assert "外部机密" not in out


def test_include_binary_skipped(tmp_path):
    binary = tmp_path / "rules" / "blob.bin"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x00\x01binary\x00")
    _write(tmp_path / "MEWCODE.md", "@include rules/blob.bin")
    out = Loader(str(tmp_path)).load()
    assert "文件不可读（二进制）" in out


def test_include_inline_kept(tmp_path):
    """不在独占行上的 @include 保持原文。"""
    _write(tmp_path / "MEWCODE.md", "段落中间的 @include keep.md 不展开")
    _write(tmp_path / "keep.md", "不应出现")
    out = Loader(str(tmp_path)).load()
    assert "@include keep.md" in out
    assert "不应出现" not in out
