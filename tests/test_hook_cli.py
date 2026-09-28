"""cli 层的 hook 接线测试（docs/ch12 T22）。

验两件事：启动期加载的 hook 真的进了 App；`run_async` 返回后兜底分派一次
SessionEnd——Ctrl+C、窗口关闭这些不走 /exit 的路径只能靠它（checklist 第 5 节）。
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from mewcode import cli

PY_CMD = f'"{sys.executable}"'


def write_config(root: Path) -> None:
    (root / ".mewcode").mkdir(exist_ok=True)
    (root / ".mewcode" / "config.yaml").write_text(
        textwrap.dedent(
            """
            providers:
              - name: a
                protocol: anthropic
                api_key: k
                model: m1
            """
        ).lstrip(),
        encoding="utf-8",
    )


def write_hooks(root: Path, marker: Path) -> None:
    """SessionStart / SessionEnd 各写一个标记文件，便于断言两者都跑过。"""
    (root / ".mewcode" / "hooks.yaml").write_text(
        textwrap.dedent(
            f"""
            hooks:
              - name: mark-start
                event: SessionStart
                action:
                  type: shell
                  command: '{PY_CMD} -c "open(r''{marker}'', ''a'').write(''start\\n'')"'
              - name: mark-end
                event: SessionEnd
                action:
                  type: shell
                  command: '{PY_CMD} -c "open(r''{marker}'', ''a'').write(''end\\n'')"'
            """
        ).lstrip(),
        encoding="utf-8",
    )


@pytest.fixture
def hooked_cli(tmp_path, monkeypatch):
    """把 App 换成不进入事件循环的桩，只验装配与退出兜底。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    write_config(tmp_path)
    marker = tmp_path / "marks.txt"

    captured: dict = {}

    async def fake_run_async(self) -> None:  # noqa: ANN001
        captured["app"] = self
        captured["rules"] = [r.name for r in self.hook_rules()]

    monkeypatch.setattr("mewcode.tui.app.MewCodeApp.run_async", fake_run_async)
    return tmp_path, marker, captured


async def test_cli_loads_hooks_and_dispatches_session_end(hooked_cli):
    """启动期加载 hook 进 App；退出后兜底分派 SessionEnd。"""
    root, marker, captured = hooked_cli
    write_hooks(root, marker)

    code = await cli._amain()

    assert code == 0
    assert captured["rules"] == ["mark-start", "mark-end"]  # 两条都进了 App
    marks = marker.read_text(encoding="utf-8").split()
    # SessionStart 由 App.on_mount 触发，但桩 run_async 没跑 Textual 事件循环，
    # 所以这里只断言退出兜底的 SessionEnd 确实执行了
    assert "end" in marks


async def test_cli_without_hooks_dispatches_nothing(hooked_cli):
    """没配 hook 时退出兜底是空操作，不报错（N9）。"""
    code = await cli._amain()
    assert code == 0
    assert not (hooked_cli[1]).exists()
