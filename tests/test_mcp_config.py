"""mcp/config 模块单测（docs/ch07 T2）：两层合并 / ${VAR} 展开 / 字段校验 / 降级。"""

import textwrap
from pathlib import Path

import pytest

from mewcode.mcp import Config, load_config


@pytest.fixture
def home(tmp_path, monkeypatch):
    """把 Path.home() 重定向到临时目录，隔离真实用户配置。"""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
    return home_dir


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_missing_both(tmp_path, home):
    cfg = load_config(str(tmp_path))
    assert isinstance(cfg, Config)
    assert cfg.servers == {}


def test_user_only(tmp_path, home):
    write(
        home / ".mewcode" / "config.yaml",
        """
        mcp_servers:
          a:
            type: stdio
            command: echo
        """,
    )
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"a"}
    assert cfg.servers["a"].type == "stdio"
    assert cfg.servers["a"].command == "echo"


def test_project_only(tmp_path, home):
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          b:
            type: http
            url: "http://localhost:8080/mcp"
        """,
    )
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"b"}
    assert cfg.servers["b"].url == "http://localhost:8080/mcp"


def test_merge_project_wins(tmp_path, home):
    write(
        home / ".mewcode" / "config.yaml",
        """
        mcp_servers:
          a: {type: stdio, command: user-cmd}
          only-user: {type: stdio, command: u}
        """,
    )
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          a: {type: http, url: "http://p"}
          only-proj: {type: stdio, command: p}
        """,
    )
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"a", "only-user", "only-proj"}
    # 同名 a：项目级完整覆盖（type 与 url 均为项目级值，command 归零）
    assert cfg.servers["a"].type == "http"
    assert cfg.servers["a"].url == "http://p"
    assert cfg.servers["a"].command == ""


def test_invalid_layer_skipped(tmp_path, home, capsys):
    write(home / ".mewcode" / "config.yaml", "mcp_servers: [bad")
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          ok: {type: stdio, command: echo}
        """,
    )
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"ok"}
    assert "warn" in capsys.readouterr().err


def test_binary_file_never_raises(tmp_path, home, capsys):
    (tmp_path / ".mewcode.yaml").write_bytes(b"\xff\xfe\x00\x01")
    cfg = load_config(str(tmp_path))  # 不应抛异常
    assert cfg.servers == {}
    assert "warn" in capsys.readouterr().err


def test_var_expansion(tmp_path, home, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret123")
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          a:
            type: stdio
            command: npx
            args: ["-y", "@modelcontextprotocol/server-github"]
            env:
              GITHUB_TOKEN: "${GITHUB_TOKEN}"
          b:
            type: http
            url: "https://example.com/mcp"
            headers:
              Authorization: "Bearer ${GITHUB_TOKEN}"
        """,
    )
    cfg = load_config(str(tmp_path))
    assert cfg.servers["a"].env["GITHUB_TOKEN"] == "secret123"
    assert cfg.servers["b"].headers["Authorization"] == "Bearer secret123"


def test_undefined_var_empty_and_warn(tmp_path, home, monkeypatch, capsys):
    monkeypatch.delenv("NOPE", raising=False)
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          a:
            type: http
            url: "https://example.com/mcp"
            headers:
              Authorization: "Bearer ${NOPE}"
        """,
    )
    cfg = load_config(str(tmp_path))
    assert cfg.servers["a"].headers["Authorization"] == "Bearer "
    assert "undefined env var ${NOPE}" in capsys.readouterr().err


def test_no_expand_command_args(tmp_path, home, monkeypatch):
    monkeypatch.setenv("WHO", "me")
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          a:
            type: stdio
            command: "${WHO}"
            args: ["${WHO}"]
        """,
    )
    cfg = load_config(str(tmp_path))
    assert cfg.servers["a"].command == "${WHO}"
    assert cfg.servers["a"].args == ["${WHO}"]


def test_example_file_parses(tmp_path, home, monkeypatch):
    """docs/ch07/mcp-servers.example.yaml 三个 server 都能被解析。"""
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("EXAMPLE_TOKEN", "tok")
    example = Path(__file__).resolve().parents[1] / "docs" / "ch07" / "mcp-servers.example.yaml"
    dest = tmp_path / ".mewcode.yaml"
    dest.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"github", "local-sqlite", "example-http"}
    assert cfg.servers["github"].type == "stdio"
    assert cfg.servers["github"].env["GITHUB_TOKEN"] == "tok"
    assert cfg.servers["example-http"].url == "https://mcp.example.com/mcp"
    assert cfg.servers["example-http"].headers["Authorization"] == "Bearer tok"


def test_invalid_servers_skipped(tmp_path, home, capsys):
    write(
        tmp_path / ".mewcode.yaml",
        """
        mcp_servers:
          bad-type: {type: sse}
          no-type: {command: echo}
          no-cmd: {type: stdio}
          no-url: {type: http}
          ok: {type: stdio, command: echo}
        """,
    )
    cfg = load_config(str(tmp_path))
    assert set(cfg.servers) == {"ok"}
    err = capsys.readouterr().err
    assert "skip server bad-type" in err
    assert "skip server no-type" in err
    assert "skip server no-cmd" in err
    assert "skip server no-url" in err
