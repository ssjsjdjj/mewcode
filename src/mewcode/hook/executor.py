"""四类动作执行器（docs/ch12 T11，F17–F26）。

拦截信号只有两种约定表达，且**仅在拦截类事件下有意义**：
- shell：`exit code 2`，`stderr`（或 stdout）作为拒绝原因（F19）
- http：2xx 且响应体是 `{"decision":"block","reason":"..."}`（F25）

其余失败（非 0 非 2 的退出码、网络错、超时、JSON 解析失败）一律只记日志、
**不拦截**——hook 自己坏掉不该拖住 Agent（G9/N1/N2）。
"""

from __future__ import annotations

import asyncio
import json
import locale
import sys
from dataclasses import dataclass

import httpx2

from .rule import HttpAction, PromptAction, Rule, ShellAction, SubagentAction

SUBAGENT_PLACEHOLDER = "[hook subagent] not yet implemented, skipped: {name}"


@dataclass
class ExecutionResult:
    """一次动作执行的结果；三种产出互斥（拦截 / 注入文本 / 出错）。"""

    blocked: bool = False
    reason: str = ""
    prompt: str = ""
    err: Exception | None = None


def _marshal(payload: dict) -> str:
    """payload → 单行 JSON；键字典序固定，方便用户脚本直接 grep（N6）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _decode(raw: bytes) -> str:
    """子进程输出解码：优先 UTF-8，失败退回本地编码。

    Windows 上脚本往 stderr 写非 ASCII 时用的是控制台编码（GBK），按 UTF-8 解会
    得到乱码——而拒绝原因要展示给用户、还要回灌给模型，解错就等于没说。
    UTF-8 是首选（跨平台脚本的惯例），解不动才退回本地编码。
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


class Executor:
    """按动作类型分发执行。"""

    async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
        """执行一条规则的动作；任何异常都包成 `err` 返回，不向外抛。"""
        action = rule.action
        try:
            if isinstance(action, ShellAction):
                return await self._run_shell(action, payload, blocking, rule.timeout)
            if isinstance(action, PromptAction):
                return self._run_prompt(action)
            if isinstance(action, HttpAction):
                return await self._run_http(action, payload, blocking, rule.timeout)
            if isinstance(action, SubagentAction):
                return self._run_subagent(action)
            return ExecutionResult(err=TypeError(f"unknown action: {type(action).__name__}"))
        except asyncio.CancelledError:
            raise  # 取消要传播（N2）
        except Exception as exc:  # noqa: BLE001 —— hook 失败不中断主流程（G9）
            return ExecutionResult(err=exc)

    # ---- shell ----

    async def _run_shell(
        self, action: ShellAction, payload: dict, blocking: bool, timeout: float
    ) -> ExecutionResult:
        # Windows 的 ProactorEventLoop 不支持 text=True，统一收发 bytes 再解码
        try:
            proc = await asyncio.create_subprocess_shell(
                action.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return ExecutionResult(err=exc)

        try:
            async with asyncio.timeout(timeout):
                stdout_b, stderr_b = await proc.communicate(_marshal(payload).encode("utf-8"))
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecutionResult(err=TimeoutError(f"shell hook timed out after {timeout}s"))

        if blocking and proc.returncode == 2:
            # strip() 而不是 rstrip("\n")：Windows 的 echo 会带上 \r 与尾随空格
            reason = _decode(stderr_b or stdout_b).strip()
            return ExecutionResult(blocked=True, reason=reason)
        if proc.returncode == 0:
            return ExecutionResult()
        stderr = _decode(stderr_b).strip()
        return ExecutionResult(err=RuntimeError(f"exit {proc.returncode}: {stderr}"))

    # ---- prompt ----

    def _run_prompt(self, action: PromptAction) -> ExecutionResult:
        """prompt 动作永不表达拦截——即使在拦截类事件下也只做副作用（F22）。"""
        return ExecutionResult(prompt=action.text)

    # ---- http ----

    async def _run_http(
        self, action: HttpAction, payload: dict, blocking: bool, timeout: float
    ) -> ExecutionResult:
        if action.body is None:
            body = _marshal(payload)
        else:
            try:
                body = action.body.format_map(payload)
            except (KeyError, ValueError, IndexError) as exc:
                return ExecutionResult(err=ValueError(f"body template failed: {exc}"))

        method = action.method or "POST"
        try:
            async with httpx2.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, action.url, content=body, headers=action.headers
                )
        except httpx2.HTTPError as exc:
            return ExecutionResult(err=exc)

        if not (200 <= resp.status_code < 300):
            # 非 2xx：不拦截，但要记为 hook 失败（G9/T12 第 8 条）——否则一次 500
            # 会被当成「hook 检查通过」而静默放行。
            return ExecutionResult(err=RuntimeError(f"HTTP {resp.status_code}"))
        if not blocking:
            return ExecutionResult()
        try:
            data = resp.json()
        except ValueError:
            return ExecutionResult()  # 响应不是 JSON：结构不符，按放行处理（F25）
        if not isinstance(data, dict) or data.get("decision") != "block":
            return ExecutionResult()
        return ExecutionResult(blocked=True, reason=str(data.get("reason", "")))

    # ---- subagent（本期占位）----

    def _run_subagent(self, action: SubagentAction) -> ExecutionResult:
        print(SUBAGENT_PLACEHOLDER.format(name=action.agent_name), file=sys.stderr)
        return ExecutionResult()
