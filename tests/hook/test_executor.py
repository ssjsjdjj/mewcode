"""四类动作执行器测试（docs/ch12 T12，F17–F26）。

HTTP 用 `httpx2.MockTransport` 起内存桩，不拉真实网络（与 tests/test_mcp_http.py 同法）。
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx2
import pytest

from mewcode.hook import Event
from mewcode.hook.executor import Executor
from mewcode.hook.rule import HttpAction, PromptAction, Rule, ShellAction, SubagentAction


def shell_rule(command: str, *, blocking_event: bool = True, timeout: float = 30.0) -> Rule:
    return Rule(
        name="t",
        event=Event.PRE_TOOL_USE if blocking_event else Event.POST_TOOL_USE,
        action=ShellAction(command=command),
        timeout=timeout,
    )


def http_rule(action: HttpAction, *, blocking_event: bool = True) -> Rule:
    return Rule(
        name="t",
        event=Event.PRE_TOOL_USE if blocking_event else Event.STOP,
        action=action,
    )


def py(code: str) -> str:
    """用当前解释器执行一段 Python——Windows 上没有可执行的 shell 脚本。"""
    return f'"{sys.executable}" -c "{code}"'


# ---- shell ----


async def test_shell_exit_2_blocks_with_stderr_reason():
    rule = shell_rule(py("import sys; print('no writes today', file=sys.stderr); sys.exit(2)"))
    r = await Executor().run(rule, {"tool_name": "write_file"}, blocking=True)
    assert r.blocked is True
    assert r.reason == "no writes today"
    assert r.err is None


async def test_shell_exit_2_falls_back_to_stdout():
    rule = shell_rule(py("import sys; print('reason-from-stdout'); sys.exit(2)"))
    r = await Executor().run(rule, {}, blocking=True)
    assert r.blocked is True and r.reason == "reason-from-stdout"


async def test_shell_exit_0_passes():
    r = await Executor().run(shell_rule("exit 0"), {}, blocking=True)
    assert r.blocked is False and r.err is None


async def test_shell_exit_2_does_not_block_non_blocking_event():
    """exit 2 只在拦截类事件下表达拦截（F19）。"""
    r = await Executor().run(shell_rule("exit 2", blocking_event=False), {}, blocking=False)
    assert r.blocked is False
    assert isinstance(r.err, RuntimeError)
    assert "exit 2" in str(r.err)


async def test_shell_other_nonzero_is_error_not_block():
    r = await Executor().run(shell_rule("echo boom >&2 && exit 1"), {}, blocking=True)
    assert r.blocked is False
    assert isinstance(r.err, RuntimeError)
    assert "boom" in str(r.err)


async def test_shell_receives_sorted_json_on_stdin(capsys):
    """payload 以键字典序的单行 JSON 从 stdin 传入（N6）。"""
    rule = shell_rule(f"{py('import sys; sys.stderr.write(sys.stdin.read())')} && exit 2")
    r = await Executor().run(rule, {"zeta": 1, "alpha": {"b": 2}}, blocking=True)
    assert r.blocked is True
    assert r.reason == '{"alpha": {"b": 2}, "zeta": 1}'


async def test_shell_timeout_is_error():
    rule = shell_rule(f"{py('import time; time.sleep(10)')}", timeout=0.3)
    r = await Executor().run(rule, {}, blocking=True)
    assert isinstance(r.err, TimeoutError)
    assert r.blocked is False


async def test_shell_startup_failure_is_error():
    r = await Executor().run(shell_rule("__no_such_command_xyz__"), {}, blocking=True)
    assert isinstance(r.err, (OSError, RuntimeError))


# ---- prompt ----


async def test_prompt_action_injects_text():
    rule = Rule(name="p", event=Event.SESSION_START, action=PromptAction(text="用 zh-CN 回复"))
    r = await Executor().run(rule, {}, blocking=False)
    assert r.prompt == "用 zh-CN 回复"
    assert r.blocked is False and r.err is None


async def test_prompt_never_blocks_even_on_blocking_event():
    """prompt 动作永不表达拦截（F22）。"""
    rule = Rule(name="p", event=Event.PRE_TOOL_USE, action=PromptAction(text="tip"))
    r = await Executor().run(rule, {}, blocking=True)
    assert r.blocked is False and r.prompt == "tip"


# ---- http ----


@pytest.fixture
def serve(monkeypatch):
    """把 httpx2.AsyncClient 换到 MockTransport；返回 (install, seen)。"""
    seen: list[dict] = []
    orig = httpx2.AsyncClient
    state: dict = {}

    def _install(status: int = 200, body: str = "{}", content_type: str = "application/json"):
        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(
                {
                    "url": str(request.url),
                    "method": request.method,
                    "headers": dict(request.headers),
                    "content": request.content.decode("utf-8"),
                }
            )
            return httpx2.Response(status, text=body, headers={"content-type": content_type})

        state["handler"] = handler
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: orig(transport=httpx2.MockTransport(state["handler"]), **kw),
        )

    _install()
    return _install, seen


async def test_http_block_decision(serve):
    install, seen = serve
    install(body='{"decision":"block","reason":"network policy"}')
    r = await Executor().run(http_rule(HttpAction(url="http://x/check")), {}, blocking=True)
    assert r.blocked is True and r.reason == "network policy"
    assert seen[0]["method"] == "POST"  # 缺省方法
    assert json.loads(seen[0]["content"]) == {}  # 缺省 body = payload JSON


async def test_http_non_block_decision(serve):
    install, seen = serve
    install(body='{"decision":"allow"}')
    r = await Executor().run(http_rule(HttpAction(url="http://x/check")), {}, blocking=True)
    assert r.blocked is False and r.err is None


async def test_http_5xx_is_error_not_block(serve):
    install, _ = serve
    install(status=500, body="boom")
    r = await Executor().run(http_rule(HttpAction(url="http://x/check")), {}, blocking=True)
    assert r.blocked is False
    assert isinstance(r.err, RuntimeError) and "500" in str(r.err)


async def test_http_decision_block_ignored_when_not_blocking(serve):
    """非拦截类事件的 2xx 响应体即使是 block 也不拦截（F25 的前提）。"""
    install, _ = serve
    install(body='{"decision":"block","reason":"x"}')
    r = await Executor().run(
        http_rule(HttpAction(url="http://x/notify"), blocking_event=False), {}, blocking=False
    )
    assert r.blocked is False and r.err is None


async def test_http_body_template(serve):
    """JSON 模板要写 `{{` 转义——`{` 是 str.format_map 的占位符语法（F23）。

    `{{` / `}}` 才是字面花括号，这是 `str.format` 的固有代价，配置示例里会写清楚。
    """
    install, seen = serve
    install()
    rule = http_rule(
        HttpAction(url="http://x/notify", body='{{"event":"{event}","tool":"{tool_name}"}}')
    )
    await Executor().run(rule, {"event": "Stop", "tool_name": "bash"}, blocking=True)
    assert json.loads(seen[0]["content"]) == {"event": "Stop", "tool": "bash"}


async def test_http_body_template_with_raw_json_braces_is_loud_error(serve):
    """忘记转义 → 明确报错，不静默发出坏请求。"""
    install, seen = serve
    install()
    rule = http_rule(HttpAction(url="http://x/notify", body='{"event":"{event}"}'))
    r = await Executor().run(rule, {"event": "Stop"}, blocking=True)
    assert isinstance(r.err, ValueError)
    assert "template failed" in str(r.err)
    assert seen == []  # 没发出请求


async def test_http_headers_passed(serve):
    install, seen = serve
    install()
    rule = http_rule(HttpAction(url="http://x/h", headers={"Authorization": "Bearer t"}))
    await Executor().run(rule, {}, blocking=True)
    assert seen[0]["headers"]["authorization"] == "Bearer t"


async def test_http_body_template_missing_key_is_error(serve):
    install, _ = serve
    install()
    rule = http_rule(HttpAction(url="http://x/h", body='{"a":"{nope}"}'))
    r = await Executor().run(rule, {"event": "Stop"}, blocking=True)
    assert isinstance(r.err, ValueError)
    assert "template failed" in str(r.err)


async def test_http_network_error_is_error(monkeypatch):
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    orig = httpx2.AsyncClient
    monkeypatch.setattr(
        httpx2, "AsyncClient", lambda **kw: orig(transport=httpx2.MockTransport(boom), **kw)
    )
    r = await Executor().run(http_rule(HttpAction(url="http://x/down")), {}, blocking=True)
    assert isinstance(r.err, httpx2.HTTPError)
    assert r.blocked is False


# ---- subagent（占位）----


async def test_subagent_placeholder_logs_and_passes(capsys):
    rule = Rule(
        name="sa",
        event=Event.SESSION_START,
        action=SubagentAction(agent_name="foo", prompt="test"),
    )
    r = await Executor().run(rule, {}, blocking=False)
    assert r.blocked is False and r.err is None and r.prompt == ""
    assert "[hook subagent] not yet implemented, skipped: foo" in capsys.readouterr().err


# ---- 取消要传播 ----


async def test_cancelled_error_propagates(monkeypatch):
    """hook 执行被取消时必须向上抛，不能吞成 err（N2）。"""

    class CancelExecutor(Executor):
        async def _run_shell(self, action, payload, blocking, timeout):  # noqa: ANN001
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await CancelExecutor().run(shell_rule("true"), {}, blocking=True)


async def test_reason_decoded_from_non_utf8_stderr():
    """Windows 上脚本按控制台编码（GBK）写 stderr 时，原因不能变成乱码。

    拒绝原因要展示给用户、还要回灌给模型，解错等于没说——所以解码优先 UTF-8，
    失败退回本地编码。
    """
    code = (
        "import sys; "
        "sys.stderr.buffer.write('写文件被拦'.encode('gbk')); "
        "sys.stderr.buffer.flush(); sys.exit(2)"
    )
    r = await Executor().run(shell_rule(py(code)), {}, blocking=True)
    assert r.blocked is True
    assert r.reason == "写文件被拦"
