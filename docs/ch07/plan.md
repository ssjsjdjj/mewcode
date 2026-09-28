# MCP 客户端 Plan> 技术栈：Python 3.12+；使用 **官方 SDK** `mcp`（`pip install mcp` / `uv add mcp`，import 名 `mcp`）承载协议层（JSON-RPC 编解码、`initialize` 握手、stdio 与 Streamable HTTP 传输）。本章新增 **`mewcode.mcp` 子包** 与入口装配，**不改 tool / agent / tui / permission / llm / config / conversation / prompt**。
## 架构概览- **`mewcode.mcp` 子包（新增）**：承载 MCP 客户端的全部职责——配置加载与两层合并、`${VAR}` 展开、字段校验、调用 SDK 建立 stdio / HTTP 会话、把远端工具适配成内置 `Tool` 协议、统一管理生命周期。仅依赖 `mewcode.tool`、SDK 与标准库；不依赖 agent / tui / permission / conversation。
- **`mewcode.cli`（改造）**：在 `tool.default_registry()` 之后、`permission.PermissionEngine(...)` 与 `MewCodeApp(...).run()` 之前，加载 mcp 配置 → 启动 Manager → 把 Manager 产出的工具注册进 registry → 退出时 `await manager.close()`（包在 `try/finally` 中）。
- **`mewcode.tool` 包（零改）**：`Registry.register` 与 `Tool` 协议本就是开放抽象，直接吃 `McpTool` 实例；`is_read_only` 对 MCP 工具返回正确值。
- **agent / tui 包（零改）**：工具流转链路对工具来源透明。
- **permission 包（无行为性改动，`rule.py` 增补工具名通配）**：`friendly_name` 对未知名原样返回 → 规则可写 `mcp__<server>__<tool>` 精确名或 `mcp__<server>__*` 通配；`categorize` 在 `read_only==True` 时走 CategoryRead、否则归 CategoryExec → 模式兜底矩阵自然命中；`extract_target` 对未知工具返回 `("", False, False)`，黑名单与沙箱自动跳过。通配为纯增量：规则工具名含 `*?[` 时按 glob 匹配，否则维持精确相等（ch06 行为不变）。
- **llm / provider（零改）**：工具定义透传，协议无关。

数据流（单次调用）：
```
agent.execute_batched(calls, mode)
  └→ engine.check(...)  → Allow → registry.execute(name, args)
       └→ McpTool.execute(args)                        [本章新增工具实现]
            ├→ await asyncio.wait_for(..., timeout=30)
            ├→ session.call_tool(remote_name, arguments=map)
            └→ 拼接 text content / 映射 is_error / 协议错转 is_error
       └→ ToolResult(content, is_error)                ── 回灌 conv
```
## 核心数据结构### `mewcode.mcp.Config` / `mewcode.mcp.ServerConfig`（对外）
```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ServerConfig:
    """单个 MCP server 的完整定义（已展开 ${VAR}、已校验）。"""
    type: Literal["stdio", "http"]
    command: str = ""                       # stdio 必填
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                           # http 必填
    headers: dict[str, str] = field(default_factory=dict)

@dataclass
class Config:
    """mcp_servers 在内存中的归一化形式（已合并）。"""
    servers: dict[str, ServerConfig] = field(default_factory=dict)
```
### `mewcode.mcp.Manager`（对外不透明）
```python
import asyncio
from contextlib import AsyncExitStack
from mcp import ClientSession

class Manager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []        # 成功建立的会话（供 close）
        self._tools: list[McpTool] = []            # 适配好的工具（供 cli 注册）
        self._stack = AsyncExitStack()             # 持有 stdio / http 上下文，close 时统一退栈

@dataclass
class _Session:
    name: str
    session: ClientSession
```
### 工具适配（包内私有）
```python
# McpTool 实现 mewcode.tool.Tool 协议。
@dataclass
class McpTool:
    full_name: str                    # "mcp__<server>__<tool>"
    remote_name: str                  # server 上的原始工具名
    description: str
    parameters: dict[str, Any]        # JSON Schema 透传
    read_only: bool                   # 仅来自远端 annotations.readOnlyHint==True
    caller: CallerSession             # 协议形式持有，便于单测注入 stub

class CallerSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> CallToolResult: ...
```
## 核心接口

```python
# 加载并合并两层配置；返回归一化的 Config。
# - root: 项目根（用来定位 <root>/.mewcode.yaml）
# - 文件不存在 → 视为空层；格式非法 → 跳过该层 + stderr 告警（降级，N1）
# - 内部完成 ${VAR} 展开与字段校验（非法 server 直接剔除，N2）
# - 永不抛出（签名只返 Config）
def load_config(root: str) -> Config: ...

# 启动 Manager：并发连接所有 server，每个 server 30s 超时，失败仅跳过 + 告警。
# 阻塞直到所有 server 的尝试结束（成功 / 失败 / 超时）。
# version 透传到 Implementation.version（便于 server 端识别 mewcode 版本）。
async def new_manager(cfg: Config, version: str) -> Manager: ...

# 返回适配好的工具列表（按 server 名 → 工具名 稳定排序）。
def Manager.tools(self) -> list[McpTool]: ...

# 关闭所有会话（stdio 子进程终止、HTTP DELETE）；总超时 5s 兜底，绝不阻塞退出。
async def Manager.close(self) -> None: ...
```
## 模块设计### `src/mewcode/mcp/config.py`**职责：** 加载两层 YAML、合并、展开 `${VAR}`、校验。**关键点：**
- 内部 `@dataclass class _RawServer`（含全部可能字段：type / command / args / env / url / headers，可选）。
- `_load_file(path: Path) -> dict[str, _RawServer]`：
  - 文件不存在 → 返回空 `{}`；
  - 读 / `yaml.safe_load` 失败 → stderr 告警一行 + 返回空 `{}`（调用方降级）；
  - 取 `mcp_servers` 段，缺失视为空。
- `_expand_vars(s: str) -> tuple[str, list[str]]`：正则 `\$\{([A-Za-z_][A-Za-z0-9_]*)\}`，用 `os.environ.get` 取值；未定义变量名记录到 `undefined`（供告警）。**仅作用于 env / headers 的值**。
- `_apply_expansion(name: str, srv: _RawServer) -> None`：对 `srv.env`、`srv.headers` 每个值跑 `_expand_vars`；未定义变量在 stderr 输出 `[mcp] warn: undefined env var ${X} referenced by server <name>`（同 server 同变量限一次，用局部 `set` 去重）。
- `_merge_servers(user: dict, project: dict) -> dict`：复制 user，遍历 project，同名直接整对象覆盖。
- `_validate_server(name: str, srv: _RawServer) -> ServerConfig | None`：
  - `srv.type` 必为 `"stdio"` 或 `"http"`，否则跳过；
  - `stdio` 必填 `command`；`http` 必填 `url`；缺失则跳过；
  - 违规时 stderr 告警 `[mcp] warn: skip server <name>: <reason>`。
- `load_config(root: str) -> Config`：
  - 用户级 = `Path.home() / ".mewcode" / "config.yaml"`；项目级 = `Path(root) / ".mewcode.yaml"`。
  - 两层各自 `_load_file` + `_apply_expansion`；任一层解析失败 stderr 一行告警并跳过（该层视为空）。
  - `_merge_servers` 后逐个 `_validate_server`，组装 `Config`。
### `src/mewcode/mcp/manager.py`**职责：** 连接 server、缓存会话、关闭。**关键点：**
- `connect_timeout`、`close_timeout` 作为模块级变量（非常量），便于单测临时改小，结束 restore。生产值 30s / 5s。
- `async def new_manager(cfg: Config, version: str) -> Manager`：
  - 内部 `mgr = Manager()`；为每个 `(name, srv)` 起一个 task：`asyncio.create_task(_connect_one(mgr, name, srv, version))`。
  - `await asyncio.gather(*tasks, return_exceptions=True)`（异常吸收，单 server 出错不影响其它）；
  - 全部完成后稳定排序 `mgr._tools`（按 `full_name`）。
- `async def _connect_one(mgr, name, srv, version)`：
  - `try: await asyncio.wait_for(_do_connect(mgr, name, srv, version), timeout=connect_timeout)`；
  - `except asyncio.TimeoutError`: stderr 告警 `[mcp] warn: connect server <name> timeout after 30s` 并 return；
  - `except Exception as e`: stderr 告警 `[mcp] warn: connect server <name> failed: <e>` 并 return。
- `async def _do_connect(mgr, name, srv, version)`：
  - 按 `srv.type` 构造 transport 上下文：
    - **stdio**：
      ```python
      from mcp import StdioServerParameters
      from mcp.client.stdio import stdio_client
      params = StdioServerParameters(
          command=srv.command,
          args=srv.args,
          env={**os.environ, **srv.env},   # 同名宿主变量被覆盖
      )
      ctx = stdio_client(params)
      ```
    - **http**：
      ```python
      from mcp.client.streamable_http import streamablehttp_client
      ctx = streamablehttp_client(srv.url, headers=srv.headers or None)
      ```
  - 用一个**包级 `AsyncExitStack`**（挂在 `Manager._stack`）持有 transport 与 `ClientSession` 上下文：
    ```python
    transport = await mgr._stack.enter_async_context(ctx)
    read, write = transport[0], transport[1]    # http 返回 3 元组，第三个是 metadata
    session = await mgr._stack.enter_async_context(
        ClientSession(read, write, client_info=Implementation(name="mewcode", version=version))
    )
    await session.initialize()                  # 握手
    listed = await session.list_tools()
    ```
  - 对 `listed.tools` 中每个 `Tool` 调 `adapt_tool(name, t, session)`；成功的入临时 list。
  - 在 `async with mgr._lock:` 内统一 append `_sessions` / `_tools`。
- `async def Manager.close(self)`：
  - 用 `asyncio.wait_for(self._stack.aclose(), timeout=close_timeout)` 包裹；
  - `TimeoutError` → stderr 告警 `[mcp] warn: close timeout (5s), some sessions may leak`，不再等。
- `Manager.tools()`：返回 `list(self._tools)` 副本（防外部修改）。
### `src/mewcode/mcp/tool.py`**职责：** 把 SDK 返回的 `mcp.types.Tool` 适配为 mewcode `Tool` 协议。**关键点：**
- 包级 `_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")`。
- 包级 `_non_text_warn_once: set[str] = set()`，配 `asyncio.Lock`（或在单线程 asyncio 中直接用 set）记录已告警的 `full_name`。
- `def adapt_tool(server_name: str, t: mcp.types.Tool, session: CallerSession) -> McpTool | None`：
  - `full_name = f"mcp__{server_name}__{t.name}"`。
  - **禁用字符校验**：`_VALID_NAME.fullmatch(full_name)` 不通过 → 返回 `None` + stderr 告警 `[mcp] warn: skip tool <full_name>: name contains illegal characters`。
  - `description`：`t.description` 为空时兜底 `f"来自 MCP server {server_name} 的工具 {t.name}"`。
  - `parameters`：`t.inputSchema` 转 `dict[str, Any]`（已是 dict 则 `dict(...)` 浅拷贝；为空时给 `{"type": "object"}` 兜底，避免 provider 拒收）。
  - `read_only`：`bool(t.annotations and t.annotations.readOnlyHint)`（None-safe）。
- `McpTool.name / description / parameters / read_only`：通过 dataclass 字段直接暴露（mewcode `Tool` 协议要求的属性/方法返回字段值）。
- `async def McpTool.execute(self, args: dict[str, Any] | None) -> ToolResult`：
  - `arg_map = args if args else None`（空 dict / None 视作无参数）；
  - ```python
    try:
        result = await asyncio.wait_for(
            self.caller.call_tool(self.remote_name, arg_map),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return ToolResult(content="MCP 工具调用超时 (30s)", is_error=True)
    except Exception as e:
        return ToolResult(content=f"MCP 工具调用失败: {e}", is_error=True)
    ```
  - 遍历 `result.content`：`isinstance(block, mcp.types.TextContent)` → 收集 `block.text`；其余块计数，首次出现时 stderr 告警 `[mcp] warn: tool <full_name> returned non-text content blocks (dropped)`（per `full_name` 限一次）。
  - 用 `"\n".join(texts)` 拼出 `content`；返回 `ToolResult(content=content, is_error=bool(result.isError))`。
### `src/mewcode/cli.py`（改造）
位置：在 `registry = tool.default_registry()` 之后、`PermissionEngine(...)` 之前插入：
```python
import asyncio
from mewcode import mcp as mcp_client

async def _amain() -> int:
    ...
    registry = tool.default_registry()
    mcp_cfg = mcp_client.load_config(root)
    mcp_mgr = await mcp_client.new_manager(mcp_cfg, version=__version__)
    try:
        for t in mcp_mgr.tools():
            registry.register(t)
        engine = PermissionEngine(root)
        app = MewCodeApp(cfg.providers, registry=registry, engine=engine)
        await app.run_async()
    finally:
        await mcp_mgr.close()
    return 0

def main() -> None:
    raise SystemExit(asyncio.run(_amain()))
```
（`root` 复用现有 `os.getcwd()` 结果；version 复用 `__version__`。）
## 文件组织

```
mewcode/
├── pyproject.toml                       — 改：dependencies 增加 "mcp>=1.0"
├── src/mewcode/
│   ├── mcp/
│   │   ├── __init__.py                  — 新：暴露 Config / ServerConfig / Manager / load_config / new_manager
│   │   ├── config.py                    — 新：Config / ServerConfig、load_config、_load_file、_expand_vars、_merge_servers、_validate_server
│   │   ├── manager.py                   — 新：Manager、new_manager（并发 + 30s 超时）、close（5s 兜底）、tools；模块级 connect_timeout / close_timeout
│   │   └── tool.py                      — 新：CallerSession Protocol、McpTool、adapt_tool、execute
│   └── cli.py                           — 改：装配 Manager，注册 MCP 工具，finally 关闭
├── tests/
│   ├── test_mcp_config.py               — 新：两层合并 / 变量展开 / 字段校验 / 降级 单测
│   ├── test_mcp_tool.py                 — 新：命名拼接 / 禁用字符 / Execute 各分支（成功/远端 IsError/超时/协议错/非 text 块）
│   └── test_mcp_manager.py              — 新：连接成功/失败/超时、close 不死锁、共享状态并发安全
├── docs/ch07/
│   ├── spec.md / plan.md / task.md / checklist.md
│   └── mcp-servers.example.yaml         — 新：配置示例（用 ${VAR}）
└── （其它包零改）
```
## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 协议层实现 | 官方 Python SDK（`mcp`，PyPI 包名 `mcp`） | 用户拍板；避免自研 JSON-RPC / 握手 / 帧；SDK 已处理 stdio (`stdio_client`) 与 Streamable HTTP (`streamablehttp_client`) |
| 配置文件位置 | 项目级 `<root>/.mewcode.yaml` + 用户级 `~/.mewcode/config.yaml` | 用户拍板；项目级 dotfile 一眼可见、与现有 `.mewcode/config.yaml`（providers 凭据）分离 |
| 配置层数 | 仅两层，无本地级 | 用户拍板；`${VAR}` 已让密钥不入配置，本地层冗余 |
| 合并语义 | server 名维度，项目级完整覆盖 | 避免字段级半合并出畸形 server |
| server 类型字段 | 显式 `type: stdio\|http` | 不靠字段嗅探（防止误判）；未来扩展易加（如 sse） |
| 变量展开范围 | 仅 env / headers 的值 | 避免 command / args / server 名 / 工具名被环境间接影响；凭据走 env / headers 已足够 |
| 未定义变量 | 空串 + 一次性告警（不阻断） | server 自决无凭据时是否能跑；mewcode 不替它拍板 |
| 工具命名 | `mcp__<server>__<tool>` | 用户拍板；Claude Code 风格；LLM 工具名安全字符；一眼识别来源 |
| 启动连接策略 | 同步进 TUI 前完成 + `asyncio.gather` 并发每 server `asyncio.wait_for(30s)` 超时 + 失败跳过 | 进 TUI 时工具集稳定；asyncio 并发缩短总时延；隔离避免单 server 拖死启动 |
| 调用超时 | 30s 硬编码 `asyncio.wait_for`，转 is_error | 与连接同值；不中断 Loop；避免长卡 |
| readOnly 适配 | 严格只信 `annotations.readOnlyHint==True` | 默认走 Ask，最严；声明只读才放行 |
| 资源 / 提示词 / 采样 / roots | 不实现 | 本章只覆盖工具能力 |
| 独立 SSE 通道 | 不订阅（不消费 `streamablehttp_client` 返回的服务端推送流） | 只用请求-响应；省一条长连接；减少复杂度 |
| 非 text 内容块 | 静默丢弃 + 一次性告警 | 模型只能消费文本；丢弃比假装回灌更诚实 |
| 错误回灌 | 协议错 / 超时均转 is_error | 与 ch04 / ch05 不中断 Loop 契约一致 |
| 退出关闭 | 单一 `AsyncExitStack.aclose()` + 5s `wait_for` 兜底 | 让 SDK 的 async context 管理器统一收尾；避免某 server 卡死阻塞退出 |
| permission 接入方式 | 零改动；靠 `friendly_name` 原样 + `categorize` 按 read_only 优先 | 复用现成链路；权限规则可写 `mcp__server__tool` 与 `mcp__server__*` |
| HTTP 自定义 headers | SDK 的 `streamablehttp_client(url, headers=...)` 原生支持 | 不引入额外抽象 |
| OAuth | 不实现完整流程 | 用户预换 token 写 headers；本章范围最小化 |
| execute 接口注入 | `McpTool` 持 `CallerSession` Protocol 而非具体 `ClientSession` | 单测可注入 stub；生产代码无运行时开销 |
## 模块交互

```
cli._amain()
  ├─ tool.default_registry()                       # 6 内置工具
  ├─ mcp.load_config(root)                         # 读两层 yaml + ${VAR} 展开 + 校验
  ├─ await mcp.new_manager(cfg, version)           # asyncio.gather 并发连接所有 server，30s/各
  │     └─ 对每个 server：
  │         ├─ 构造 transport（stdio: stdio_client / http: streamablehttp_client）
  │         ├─ 进入 ClientSession 上下文
  │         ├─ await session.initialize()          # 握手
  │         ├─ await session.list_tools()
  │         └─ adapt_tool 包装成 McpTool
  ├─ for t in mgr.tools(): registry.register(t)
  ├─ PermissionEngine(root)
  ├─ await MewCodeApp(...).run_async()
  └─ finally: await mgr.close()                    # AsyncExitStack.aclose() + 5s 兜底
```

调用链（Agent 视角，工具来源透明）：
```
agent.execute_batched(calls, mode)
  └ engine.check(mode, call, registry.is_read_only(call.name))
       (MCP 工具：friendly_name 原样；categorize：read_only==True→Read, 否则→Exec；
        extract_target(未知工具)→is_file=False, target="" → 黑名单/沙箱自动跳过)
  └ Allow → registry.execute(name, args)
       └ McpTool.execute(args)
            ├ asyncio.wait_for(..., timeout=30)
            └ session.call_tool → 拼接 text / 映射 is_error / 协议错转 is_error
  └ ToolResult 回灌 conv
```

依赖方向（无环）：`mewcode.cli → mewcode.mcp → {mewcode.tool, mcp(SDK), 标准库}`；`mewcode.mcp` 不依赖 agent / tui / permission / conversation。
---

# 追加：工具延迟加载 + ToolSearch（2026-09-23）

> 本节追加于 ch07 主体实现并验收之后。F/N/AC 编号接续上文（上文止于 F12 / N8 / AC15）。上文所有条目继续有效，本条既不修改也不废止其中任何一条。

## 架构概览（分层）

```
① 入口层  mewcode.cli          —— 装配 registry，按需注册 tool_search（F16）
② 配置层  mewcode.config       —— 不涉及
③ LLM 协议层 mewcode.llm       —— 不涉及（reminder 通道复用既有能力）
④ 会话层  mewcode.conversation —— 不涉及
⑤ 提示词/资源 mewcode.prompt   —— 不涉及（清单正文由 tool 层构造，prompt 只负责包裹）
⑥ 终端层  mewcode.tui          —— app/commands/resume 三处改走统一入口

         mewcode.mcp  —— MCP 客户端（config / manager / tool）
         mewcode.tool —— 工具抽象、注册中心、延迟加载视图、tool_search
         mewcode.agent—— 唯一的请求组装点，消费「可见定义 + 清单」
```

（章节正文的架构概览见上文「MCP 客户端」主体；本节为追加功能的**增量**部分，编号 F13–F24 / AC16–AC27 与 spec 追加段一一对应。）

### 组件划分

追加功能只引入两个新组件，其余都是对既有组件的**接线**：

- **延迟加载视图（Discovery）**：会话内存态。持有注册中心引用，负责回答三个问题——本轮该注入哪些完整定义、名字清单正文是什么、某个名字被拉取/搜索后如何变更状态。它不执行工具、不碰网络、不落盘。
- **ToolSearch 工具（ToolSearchTool）**：一个普通的内置工具，`read_only = True`、`deferrable = False`。它把「拉取」与「搜索」两个动作暴露给模型，动作的实现在 Discovery 里。

被改动的既有组件：`Tool` 协议（新增一个声明成员）、`Registry`（新增一个只读的延迟声明查询）、`McpTool`（声明可延迟）、`Agent`（注入点从「全量」改为「可见定义 + 清单」）、`MewCodeApp`（持有一个 Discovery，并提供唯一入口）、三个 `defs` 调用点改为走该入口。

---

## 核心数据结构

### Tool 协议上的新成员

```
deferrable: bool        # 该工具是否允许被延迟加载
```

- **内置 6 个工具 + ToolSearchTool：`False`**（常驻，F13/G4）
- **McpTool：`True`**（F13）
- 语义：`True` 只表示「允许被延迟」，是否真的延迟由 Discovery 按「是否已发现」决定（F14）。

读取方式：注册中心与视图一律走 `getattr(tool, "deferrable", False)`。**默认 `False` = 不延迟 = 旧行为**，这样测试里的假工具（不关心延迟）无需改动即可继续通过，且第三方实现漏声明时的失败方向是「多注入」而非「工具消失」。

### Manifest（名字清单）

不是独立类型，是 Discovery 的一个方法产出的**纯文本正文**：

```
以下 MCP 工具尚未加载完整定义，需要时用 tool_search 获取：
- select:<完整工具名>  精确拉取
- 关键词              模糊搜索（最多返回 5 个）

[filesystem]
- mcp__filesystem__read_file
- mcp__filesystem__write_file
[github]
- mcp__github__search_repos
```

- 按 server 名分组、组内按完整工具名排序（N11：不依赖 dict/set 迭代序）
- **不设条数上限**（F15：截断会让被截断的工具永久不可达）
- 无可延迟且未拉取的工具时返回 `None` —— 调用方据此**完全不追加**（F15/G4 的字节级不变）
- 只含**名字**，不含 description、不含 schema（G1 的省 token 来源）

### Discovery 的方法接口

```
Discovery(registry: Registry)

has_deferrable() -> bool
    是否至少存在一个 deferrable 工具（cli 据此决定要不要注册 tool_search，F16）

deferred_names() -> list[str]
    可延迟且尚未拉取的工具完整名，按注册顺序（F14/F15）

visible_definitions(plan_only: bool) -> list[ToolDefinition]
    本轮应注入的完整定义。plan_only=True 时先取只读子集再过滤（F22）。
    = 非可延迟的（按 plan_only 过滤后）+ 可延迟且已拉取的
    相对顺序 = 注册顺序（F14）

manifest() -> str | None
    见上

select(name: str) -> Result
    精确拉取。命中 → 标记已发现 + 返回该工具的完整定义（F17）
    未命中 → is_error 结果，**不抛异常**（F17/AC19）

search(keyword: str) -> Result
    关键词搜索（F18）。命中列表，零命中为 is_error 结果；命中的全部标记已发现

reset() -> None
    清空已发现集合（F19）
```

> `plan_only: bool` 而非 `Mode`：`Mode` 定义在 `mewcode.permission`，tool 层不该反向依赖权限包。布尔参由调用方（agent / tui，两者本就已经 `import Mode`）翻译。

### ToolSearchTool 的参数

```
keyword: str    # 必填。取值 "select:<完整工具名>" 走精确拉取，其余走关键词搜索
```

单参数是刻意的：模型只需记住一条调用规则，不需要在「精确」和「搜索」两个工具之间做选择——而错误的选择会让它多烧一轮（F17 与 F18 共用同一入口）。

---

## 模块设计

### 新建 `src/mewcode/tool/deferred.py`

**职责：** 延迟加载的会话内存态视图。本轮可见性判定、清单生成、拉取/搜索的状态变更。

**对外接口：** 上述 Discovery。

**依赖：** `mewcode.tool`（`Registry`、`ToolDefinition`）。**只使用 Registry 的公开只读方法**（`definitions()` / `read_only_definitions()` / `get()` / `is_read_only()` / `count()`），不触其内部字段。

**不做：** 不写文件、不发网络、不 import `mewcode.mcp`（对 MCP 完全无知——它只看到「有些工具的 `deferrable` 是 True」）、不 import `mewcode.permission`。

### 新建 `src/mewcode/tool/tool_search.py`

**职责：** 把 Discovery 的两个动作暴露成一个普通工具。

**对外接口：** 实现 `Tool` 协议：`name() -> "tool_search"`、`description()`、`parameters()`、`read_only = True`、`deferrable = False`、`execute(args) -> Result`。

- `execute` 先 `json.loads(args or "{}")` 取 `keyword`（与既有内置工具同款），为空 → `Result(is_error=True)`。
- `select:` 前缀剥离后交给 `discovery.select()`，否则交给 `discovery.search()`。
- 结构化文本一律装进 `Result.content`，**永不抛异常**——异常会中断 agent 循环，而「没找到」是正常结果不是故障。

**依赖：** `mewcode.tool`（`Discovery`、`Result`）。

### 修改 `src/mewcode/tool/__init__.py`

- `Tool` 协议新增 `deferrable` 成员声明（带文档说明：默认 False 的语义）。
- `Registry` 新增：

```
has_deferrable() -> bool        # 任一注册工具 deferrable 为 True
deferrable_names() -> list[str] # 可延迟工具的完整名，注册顺序
```

放在 `Registry` 上而不是让 Discovery 遍历 `definitions()`：注册中心才知道注册顺序，且这是纯只读查询，不改变任何既有方法的行为。

### 修改 `src/mewcode/mcp/tool.py`

`McpTool` 数据类新增字段 `deferrable: bool = True`。`adapt_tool` 无需改动（默认值即隔离层；即便将来某个 server 要求常驻，也从这里显式传 False）。

### 修改 6 个内置工具

`src/mewcode/tool/{read_file,write_file,edit_file,bash,glob_tool,grep_tool}.py` 各加一行 `deferrable` 声明，位置紧跟 `read_only`，风格与既有 `@property read_only` 一致。

### 修改 `src/mewcode/agent/agent.py`

**唯一的请求组装点**（现约 236–299 行）。改动两处：

1. **可见定义** —— `defs` 的来源从 `registry.read_only_definitions() / registry.definitions()` 变为 `discovery.visible_definitions(mode == Mode.PLAN)`。`defs` 的后续用法（`ManageInput.tool_defs`、`Request.tools`、ch08 压缩对 `tool_defs` 的消费）**一律不动**（F21）。
2. **清单正文** —— 在 `reminder` 组装处，把清单包成第二个 `system-reminder` 块拼上去：

```
parts = []
if mode == Mode.PLAN:
    parts.append(prompt.plan_reminder(full))          # 已包裹，原样
body = discovery.manifest()
if body:
    parts.append(prompt.system_reminder(body))         # 复用既有包裹函数
reminder = "\n".join(parts)
```

- 清单走 **reminder 通道**（messages 尾部），**不进 system 稳定段**：system 的 `stable` 段字节不变，既保证 F23 的字节级不变易验证，也不动 ch05 的缓存前缀。
- `prompt/` 包**零改动**（复用 `system_reminder`），不新增 `plan_reminder_body` 这类暴露内部常量的接口。
- 无 MCP 时 `body is None`，`reminder` 与改动前逐字节相同（F23/AC25）。

`Agent.__init__` 新增一个关键字参数 `discovery: Discovery | None = None`；为 `None` 时内部自建一个包住 `registry` 的 Discovery（**单一代码路径**，不做「有/无 discovery」两套分支）。其余构造点（测试）无需改动。

### 修改 `src/mewcode/tui/app.py`

- 新增属性 `self.discovery: Discovery`，在 registry 装配之后构造。
- 新增唯一入口：

```
def visible_tool_defs(self) -> list[ToolDefinition]:
    return self.discovery.visible_definitions(self._mode == Mode.PLAN)
```

### 修改 `src/mewcode/tui/commands.py`

- `clear_and_new_session()`（现 152–175 行，`/clear` 的落点）末尾加一行 `self.discovery.reset()`（F19/AC20）。这行的位置是有讲究的：必须**在**新会话建立**之后**执行，否则与 `/resume` 的重置次序不一致。
- `force_compact()`（现 114–118 行）的 `defs` 改为 `self.visible_tool_defs()`。
- `tool_count()` **不动**：`/status` 报的仍是注册总数（6 + MCP n），延迟加载改变的是「本轮注入什么」，不是「注册了什么」（N10）。

### 修改 `src/mewcode/tui/resume.py`

- 现 141–145 行的 `defs` 三元表达式改为 `app.visible_tool_defs()`。
- 该函数内**不调用** `discovery.reset()`：`/resume` 恢复的是同一进程内的会话，已发现集合按 F19 保持当前值（AC20 的反向断言）。

### 修改 `src/mewcode/cli.py`

在既有 registry 装配之后（现 51–55 行间）：

```
registry = new_default_registry()
mcp_mgr = await ...new_manager(...)
for tool in mcp_mgr.tools(): registry.register(tool)

discovery = Discovery(registry)
if discovery.has_deferrable():                      # F16：仅当存在可延迟工具
    registry.register(ToolSearchTool(discovery))    # 无常驻 MCP 时注册中心仍是 6 个
```

`discovery` 一并注入 `MewCodeApp`。**顺序敏感**：ToolSearchTool 必须在所有 MCP 工具注册完之后再判断——它自己 `deferrable=False`，不会把自己算进去（F16/AC21）。

---

## 模块交互

一轮请求的调用链（改动后的形状）：

```
TUI 提交 → Agent.run
             │
             ├─ discovery.visible_definitions(mode == PLAN)   ← 本轮注入什么
             │      └─ registry.read_only_definitions() | .definitions()   （PLAN 过滤）
             │         └─ 按 deferrable & 已发现 过滤，保持注册顺序
             │
             ├─ discovery.manifest()                          ← 本轮提示什么
             │      └─ None 或分组名字清单
             │
             ├─ Request(tools=可见定义, system=stable+env, reminder=plan提醒 + 清单)
             │
             └─ LLM 返回 tool_use: tool_search(keyword="select:mcp__x__y")
                   │
                   └─ registry.execute("tool_search", ...)     ← 普通工具，走既有路径
                         └─ ToolSearchTool.execute → discovery.select("mcp__x__y")
                               ├─ 命中：已发现集合 += {name}，返回完整定义文本
                               └─ 未命中：返回 is_error 结果（不抛）
                                    → 结果按既有工具结果回流，循环继续（F21）
                   │
                   ↓ 下一轮
                discovery.visible_definitions(...)  —— 该工具已在集合内，完整定义进入 tools
```

**关键点：** 拉取动作经由既有 Registry→工具结果回流通道完成，agent 循环**不知道** ToolSearch 与别的工具有任何区别。延迟机制对 agent 的全部影响就是上面那两个方法的返回值（F21）。

权限链路的交互：`tool_search` 是只读工具 → Plan Mode 下在只读子集内（F22）；被拉取的工具执行时走既有的五层权限判定，**权限包零改动**（F21/AC24）。

---

## 文件组织

```
src/mewcode/
├── tool/
│   ├── __init__.py       — Tool 协议 +deferrable；Registry +has_deferrable/deferrable_names
│   ├── deferred.py       — 新增：Discovery
│   ├── tool_search.py    — 新增：ToolSearchTool
│   ├── read_file.py      — +deferrable = False
│   ├── write_file.py     — +deferrable = False
│   ├── edit_file.py      — +deferrable = False
│   ├── bash.py           — +deferrable = False
│   ├── glob_tool.py      — +deferrable = False
│   └── grep_tool.py      — +deferrable = False
├── mcp/
│   └── tool.py           — McpTool +deferrable: bool = True
├── agent/
│   └── agent.py          — +discovery 参数；defs 与 reminder 两处改造
├── tui/
│   ├── app.py            — +self.discovery；+visible_tool_defs()
│   ├── commands.py       — /clear 重置；force_compact 改走入口
│   └── resume.py         — defs 改走入口（不重置）
└── cli.py                — 装配 Discovery 与 ToolSearchTool

tests/
├── test_tool_deferred.py   — 新增：Discovery 单元测试
├── test_tool_search.py     — 新增：ToolSearchTool 单元测试
├── test_ch07_deferred_e2e.py — 新增：端到端 + F24 的 token 实测脚本化
└── tools/                  — 新增：F24 用的合成 fixture（4 server × 15 工具）
```

---

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 延迟声明放哪 | 工具自己声明 `deferrable` | F13 明确要求不能按名字前缀（`mcp__`）在注册中心硬编码推断——那样内置工具改名或非 MCP 的可延迟工具接入都会失效 |
| 协议加成员会不会破坏既有代码 | 读取端用 `getattr(tool,"deferrable",False)` | 默认 False = 不延迟 = 旧行为。测试里的 5 个假工具无需改动即通过，第三方实现漏声明时失败方向是「多注入」而非「工具消失」——后者是安全且可诊断的 |
| 可见性计算放哪 | 新建 Discovery，而非给 Registry 加方法 | Registry 是「登记 + 执行」的无状态注册中心；延迟状态是**会话级内存态**，两者生命周期不同（Registry 随进程，Discovery 随会话）。混在一起就没法解释 `/clear` 为什么只重置一半 |
| 清单放 messages 还是 system | reminder 通道（messages 尾部） | ① system `stable` 段字节不变，F23 的不变式容易验证；② 不动 ch05 的缓存前缀；③ 复用既有 `system_reminder`，`prompt/` 包零改动 |
| 拉取与搜索是几个工具 | 一个 `tool_search`，`select:` 前缀区分 | 模型少一次选择就少一次选错的机会；选错要多烧一轮。且单工具的名字清单提示更短 |
| 命中上限 | 搜索 5 条、精确拉取无上限；清单无上限 | 5 是「一次暴露给模型的合理批量」；清单截断会让工具**永久不可达**，是正确性问题而非体验问题 |
| 已发现状态要不要持久化 | 不持久化，纯会话内存 | F19/G3：范围守窄。持久化会引出「跨会话的工具集合是否可信」「存档格式变更」两个新问题，与本次目标无关 |
| 搜索是否语义检索 | 纯关键词，名字命中优先于描述命中 | 无 embedding 依赖、无网络、结果确定（N11）。语义检索留给后续章节 |
| `plan_only: bool` 而非传 `Mode` | 布尔参 | `Mode` 在 `mewcode.permission`，tool 层反向依赖权限包会破坏既有依赖方向 |
| tool_search 何时注册 | 装配期一次性判断 | 避免运行期增删工具（F16 不做的事）。代价是 MCP server 热插拔不支持——本来也不支持 |
| F24 的数字口径 | 序列化字符数 ÷ 3.5 | 复用 `compact/const.py` 既有的 `ESTIMATE_CHARS_PER_TOKEN`，不引入 tokenizer 依赖。**同时声明两条局限**：估算非真实分词器；fixture 是合成的（AC27） |
| 拉取 / 搜索的返回值 | `Result` 而非裸字符串 | 「没找到」是失败结果，用结构化 `is_error` 表达比让调用方嗅探字符串内容可靠；也免了工具层重复实现命中判定 |

---

## spec 覆盖自检

| F | 归属 |
|---|------|
| F13 声明式可延迟 | Tool 协议 + 6 内置 + McpTool |
| F14 每轮组装 | `Discovery.visible_definitions` |
| F15 清单 | `Discovery.manifest` |
| F16 tool_search 条件注册 | `cli.py` + `Registry.has_deferrable` |
| F17 精确拉取 | `Discovery.select` + `ToolSearchTool` |
| F18 关键词搜索 | `Discovery.search` |
| F19 会话内存态 + 重置 | `Discovery.reset` / `commands.py` / `resume.py` 不重置 |
| F20 幂等 | `select`/`search` 用集合语义 |
| F21 只改两处 | `agent.py` 两处改造；权限/执行/压缩零改动 |
| F22 Plan Mode 叠加 | `plan_only` 参数 + `tool_search` 自身只读 |
| F23 无 MCP 字节不变 | 空 Discovery 恒等过滤 + `manifest()→None` |
| F24 可复现实测 | `tests/test_ch07_deferred_e2e.py` + fixture |

N9 纯内存构造 / N10 无回归（`tool_count` 不动）/ N11 确定性（排序 + 集合）/ N12 ruff+mypy+pytest / N13 跨 provider（不依赖任何厂商的 `defer_loading` 专有字段）——均有对应任务。
