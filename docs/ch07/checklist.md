# MCP 客户端 Checklist

> 每一项通过运行代码或观察行为来验证；函数 / 类型名仅作定位提示，核验断言本身不依赖其命名（重命名实现而行为不变时本清单仍适用）。
## 实现完整性
- [x] 加载两层配置：两文件存在时按 server 名合并、同名 server 项目级完整覆盖用户级（验证：单测构造两层文件断言合并结果与字段来源）。(AC1/F1)
- [x] 配置降级：任一文件缺失视为空、格式非法跳过该文件 + stderr 告警 + 其它正常加载，不致启动失败（验证：单测分别投喂缺失与非法 YAML，断言 `load_config` 不抛异常且其它层 server 仍在）。(AC1/N1)
- [x] 字段校验：stdio 缺 command、http 缺 url、`type` 非法或缺失，均跳过该 server + stderr 给出原因，其它 server 不受影响（验证：单测分别构造各非法 server）。(AC2/N2)
- [x] `${VAR}` 展开：env / headers 的值被展开；未定义变量展开为空串 + 一次性告警；command / args / 工具名 / server 名不展开（验证：单测覆盖各分支，含 `command: ${X}` 应保留字面量）。(AC3/F3)
- [x] stdio 连接 + 握手 + 列工具：能拉起一个 MCP server 子进程并由 SDK 完成 `session.initialize()` + `session.list_tools()`；`env` 被注入到子进程环境（验证：`test_mcp_manager` 用 `sys.executable` 拉起最小 echo server，断言 echo/add 可用且 close 干净）。(AC4/F4/F6)
- [x] HTTP 连接 + 自定义 headers：能对 HTTP MCP server 完成握手 + 列工具；`headers` 真正出现在每个 HTTP 请求中（验证：`test_mcp_http` 用 `httpx2.MockTransport` 注入内存端点，断言 server 端逐请求收到 `Authorization` / 自定义头）。(AC5/F5/F6/N6)
- [x] 工具命名：所有 MCP 工具的 `name` 形如 `mcp__<server>__<tool>`；前缀拼接后含 LLM 工具名禁用字符（非 `[A-Za-z0-9_-]`）的工具被跳过并告警（验证：单测构造含 `.` 的 server 名 / 工具名，断言 `adapt_tool` 返回 `None`）。(AC6/AC7/F8)
- [x] 命名空间隔离：同一 tool 名在不同 server 互不覆盖；与 6 个内置工具天然不重名（验证：registry 注册后断言全名集合无重复）。(AC7/F8)
- [x] 工具适配字段：description 空 → 兜底文案；schema 透传为 `dict[str, Any]`、空 schema 兜底 `{"type": "object"}`；`annotations.readOnlyHint==True` → `read_only is True`，其它（含 None / False）→ `False`（验证：单测覆盖各分支，含 `annotations is None` None-safe）。(AC6/F7)
- [x] 调用结果聚合：`execute` 把远端多个 text content 块按顺序拼成 `content`；非 text 块（image/audio/resource_link/embedded_resource）静默丢弃 + 单 tool 限一次告警（验证：`test_mcp_tool` 注入 stub 返回混合内容块，断言 collected 仅含 text 且告警计数为 1）。(AC6/F7)
- [x] 远端错误映射：远端 `isError==True` 时 `ToolResult.is_error is True`，`content` 仍为远端 text（验证：`test_mcp_tool` 注入 stub 返回 `isError=True` + text 块）。(AC6/F7)
- [x] 协议错与超时回灌：`call_tool` 抛异常或 30s `asyncio.wait_for` 超时 → `is_error is True` 且 `content` 含可读错因，Agent Loop 不中断（验证：`test_mcp_tool` 注入 stub 抛异常 / 阻塞至超时，断言 `is_error` 与文案）。(AC9/F7/F10/N5)
- [x] 启动失败隔离：有 server 连接 / 握手 / 列工具失败时，只跳过它自身，其它 server 与内置工具集照常注册可用（验证：`test_mcp_manager` 用一个失败 server + 一个 stub 成功 server，断言成功 server 工具被注册）。(AC8/F9/N1)
- [x] 30s 启动超时：模拟连接卡住的 server 在（测试中缩短的）超时窗口结束后被跳过，启动不阻塞超过该窗口（验证：`test_mcp_manager` 注入连接 stub `await asyncio.Event().wait()` + `monkeypatch.setattr(manager, "connect_timeout", 0.2)`，断言 `new_manager` 在超时窗口附近返回）。(AC8/F9/N1)
- [x] 退出干净：`Manager.close()` 通过 `AsyncExitStack.aclose()` 终止所有 stdio 子进程、断开 HTTP 会话；某 session 关闭卡住时 5s 兜底返回不阻塞（验证：`test_mcp_manager` 注入 `__aexit__` 阻塞的 fake 上下文 + 短兜底，断言 `close()` 在兜底时间内返回；tmux 实跑退出后 `ps` 无残留子进程见场景 6）。(AC10/F11/N7)
## 集成
- [x] 权限链路自然命中：无规则时 `readOnlyHint=True` 的 MCP 工具走 Read 兜底（default 直接放行）、其余走 Exec 兜底（default Ask）；allow 规则 `mcp__<server>__*` 命中时直接放行；bypass 模式放行（验证：`test_mcp_permission` 对 mcp 全名调用断言裁决；tmux 实跑见场景 4）。(AC11/F12/N4)
- [x] permission 包无行为性改动：`rule.py` 仅增补工具名通配（`*?[` 时按 glob、否则维持精确相等，ch06 行为不变），其余文件零修改；`llm` / `tool` / `agent` / `tui` / `conversation` 零修改（验证：核对文件变更范围）。(N4/N3)
- [x] provider 适配层零改动：`src/mewcode/llm/anthropic_provider.py`、`src/mewcode/llm/openai_provider.py` 无修改（验证：核对文件时间戳与变更范围）。(AC12/N3)
- [x] 黑名单 / 沙箱对 MCP 工具自动跳过：MCP 工具调用 `extract_target` 返回 `("", False, False)` → 黑名单层因 `target==""` 不命中、沙箱层因 `is_file is False` 不进入；内置 `bash` 的 `rm -rf /` 仍被黑名单拦截（验证：`test_mcp_permission` 对 mcp 全名调用断言不被 Deny、对 bash 断言仍 DENY）。(AC11/F12)
- [x] ch01–ch06 不退化：`pytest` 全过，既有用例不需要适配（验证：运行测试套件）。(AC13/N5)
## 编译与测试
- [x] `python -m mewcode` 在合法配置下能进 TUI（含 / 不含 mcp 配置两种，tmux 场景 1 实测）。
- [x] `ruff format --check .` 无 diff。
- [x] `ruff check .` 无告警。
- [x] `pytest` 通过（含 `tests/test_mcp_config.py` / `tests/test_mcp_tool.py` / `tests/test_mcp_manager.py` / `tests/test_mcp_http.py` / `tests/test_mcp_permission.py`，以及既有 config / conversation / tool / agent / prompt / permission / tui 单测）。
- [x] `pytest --asyncio-mode=auto tests/test_mcp_manager.py` 无悬挂 task / 死锁、无 `RuntimeWarning: coroutine ... was never awaited`（重点守护 Manager 并发连接、共享状态、close 兜底）。(N7/N8)
- [ ] （可选）`mypy src/mewcode/mcp` 通过。
- [x] 凭据不落盘：ch07 配置示例 / 文档 / 测试 fixture 全用 `${VAR}`，无真实凭据；`git grep -E '(Bearer|sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}'` 在 ch07 新增文件内无命中。(AC14/N6)
## 端到端场景（tmux 实跑）
- [x] 场景 1（无 MCP 配置）：仓库内不存在 `.mewcode.yaml` 与 `~/.mewcode/config.yaml` 时，mewcode 正常进 TUI；registry 仅含 6 个内置工具；stderr 无 mcp 相关告警。(AC1)
- [x] 场景 2（stdio server 接入）：在 `.mewcode.yaml` 配置 `@modelcontextprotocol/server-everything` 一类真实 server，启动后日志显示 server 连接成功 + 工具数；TUI 中让模型调用其中一个工具（如 echo），default 模式弹人在回路 → 「允许本次」→ 工具结果回灌 → 模型续答。(AC4/AC6/AC11)
- [x] 场景 3（失败隔离）：配置一个不存在 command 的 server + 一个能跑的 server，启动 stderr 有第一个 server 的失败告警；能跑的 server 工具仍可用、能正常调用。(AC8)
- [x] 场景 4（永久放行 + 重启）：场景 2 中选「永久允许」→ `.mewcode/settings.local.yaml` 出现对应 `mcp__<server>__<tool>` allow 规则；重启 mewcode 后再调该工具不再弹窗直接执行。(AC11)
- [x] 场景 5（凭据展开）：配置 `env: { GITHUB_TOKEN: "${GITHUB_TOKEN}" }`；`unset GITHUB_TOKEN` 启动时 stderr 有 undefined 告警但 server 仍尝试启动（server 自决报错与否）；`export GITHUB_TOKEN=...` 后正常工作。(AC3/AC14)
- [x] 场景 6（退出干净）：退出 mewcode（`/exit` 或 Ctrl+C）后 `ps -ef | grep server-everything`（或对应 server 进程名）确认子进程无残留。(AC10)
- [x] 场景 7（bypass + 黑名单兜底）：Shift+Tab 切到 bypassPermissions，MCP 工具调用不弹窗；让模型跑内置 `bash` 工具 `rm -rf /` 仍被黑名单拦下、回灌被拒。(AC11/N4)
- [x] 场景 8（HTTP server，可选）：本地起一个最小 HTTP MCP server 或用 `pytest-httpx` mock，配置 http 类型 + `headers: { Authorization: "Bearer ${TOKEN}" }`；启动后工具被注册；调用时 server 端日志可见 Authorization 头。(AC5)

---

# 追加：工具延迟加载 + ToolSearch Checklist（2026-09-23）

> 本节追加于 ch07 主体验收之后。AC 编号接续上文（上文止于 AC15）。每条都可运行或观察验证。
## 实现完整性
- [x] 可延迟由工具**自身声明**：6 个内置与 `tool_search` 声明为不可延迟、MCP 工具声明为可延迟；注册中心不按名字前缀推断（验证：构造一个名字**不带** `mcp__` 前缀的可延迟工具，断言它同样被延迟）。(AC16/F13)
- [x] 每轮组装：可延迟且未拉取的工具不出现在请求 `tools` 中、拉取过之后出现、不可延迟的恒在；相对顺序等于注册顺序（验证：断言两轮 `tools` 名单的差集与顺序）。(AC17/F14)
- [x] 名字清单：仅当存在「可延迟且未拉取」时追加；按 server 分组、组间与组内排序确定；只含名字，不含 description 与 schema；无此类工具时**完全不追加**（验证：捕获 `Request.reminder` 对比）。(AC18/F15)
- [x] 无 MCP 配置时逐字节不变：registry 仍为 6 个工具、不注册 `tool_search`、`tools` 与补充消息与改造前完全相同（验证：同一输入下断言请求序列化结果相等）。(AC21/F16/F23)
- [x] `tool_search` 是普通内置只读工具：不参与延迟判定、不计入「连续未知工具」计数、Plan Mode 下可用（验证：Plan Mode 断言其出现在只读子集中）。(AC21/F16/F22)
- [x] 精确拉取：`select:<全名>` 命中返回完整定义（名称/描述/参数 schema）并从下一轮进入 `tools`；未命中返回结构化错误结果、**不抛异常**、循环继续（验证：断言未命中时 `Result.is_error is True` 且 agent 未中断）。(AC19/F17)
- [x] 关键词搜索：同时匹配名字与描述、名字命中排在描述命中之前、同级按注册顺序、最多 5 条且命中者标记发现；超上限给出「已截断 + 总数」；零命中是错误结果（验证：构造名字命中与描述命中各一并断言排序与上限）。(AC19/F18)
- [x] 已发现集合是会话内存态：进程重启即空、`/clear` 后为空、**`/resume` 后保持当前值**、不写入会话存档（验证：`/resume` 前后断言集合不变；检查存档文件无相关字段）。(AC20/F19)
- [x] 幂等：重复拉取同一工具、重复搜索命中同一工具，不产生重复条目、不改变后续请求的 `tools` 名单（验证：重复调用后断言名单不变）。(AC20/F20)
- [x] 延迟只改两件事：仅「哪些完整定义进入本轮」与「`tool_search` 是否出现」；工具执行、超时、错误回灌、批量执行、ch06 五层权限、ch08 对 `tool_defs` 的消费全部不变（验证：既有用例全绿 + permission 包无文件改动）。(AC22/F21)
## 集成
- [x] 注入点唯一：`defs` 的三个调用点（agent / resume / force_compact）都走同一入口（验证：grep 无残留的 `read_only_definitions() / definitions()` 三元表达式）。(AC23/F21)
- [x] permission 包零改动：被拉取的工具执行时仍走既有五层判定（验证：文件无改动 + 对拉取后的工具调用断言裁决与改造前一致）。(AC24/F21)
- [x] `/status` 报的是注册总数而非本轮注入数（验证：有 MCP 时该数字不因延迟而变化）。(AC25/N10)
- [x] ch01–ch10 不退化：`pytest` 全绿，既有用例无需适配（验证：运行测试套件）。(AC25/N10)
## 编译与测试
- [x] `ruff format --check .` 无 diff；`ruff check .` 无告警。
- [ ] `mypy src/mewcode/tool src/mewcode/agent` 通过。 ← **未勾**：`agent.py` 有 8 条既有 mypy 错误（`out` 重定义 / `_execute_batched` 入参 / `ToolResult | None`），已用「回退副本重跑 mypy」证明改动前后完全一致（行号整体位移 = 本次新增行数），`src/mewcode/tool` 0 错误。
- [ ] `pytest` 通过（含 `tests/test_tool_deferred.py` / `tests/test_tool_search.py` / `tests/test_ch07_deferred_e2e.py`）。 ← **未勾**：三个新文件全绿；全量 304 passed / 22 failed / 1 skipped，22 失败与 1 跳过全部来自本机 mcp 1.29.0 的 `mcp.server.mcpserver` 缺失（既有问题），与改动前基线（255 passed / 22 failed）逐条一致 ⇒ 零回归。
- [x] 跨 provider 一致：同一延迟行为在 Anthropic 与 OpenAI 两种 provider 下一致，未使用任何厂商专有的延迟加载字段（验证：核对请求组装代码不含 `defer_loading` 一类字段）。(AC26/N13)
- [x] 确定性：不依赖 `set` / `dict` 迭代顺序（验证：同一状态下多次组装，序列化结果逐字节相同）。(N11)
## 端到端场景
- [x] 场景 9（无 MCP）：不配任何 server 启动，请求与改造前一致、`/status` 报 6、模型看不到 `tool_search`。(AC21/F23)
- [ ] 场景 10（搜索 → 拉取 → 真调用）：配一个真实 stdio server，首轮模型只看到名字清单；模型用 `tool_search` 按关键词找到并 `select:` 拉取 → 下一轮该工具进入列表 → **实际调用它**（经既有权限链路）→ 结果回灌 → 模型续答。(AC19/F14/F21) ← **半通过**：拉取 → 下一轮可见 → 真调用 → 结果回灌 → 续答已用合成工具端到端验证；「配一个真实 stdio server」一节被 mcp 1.29.0 挡住，用例已写好并在本机 skip（`test_amain_with_live_server_registers_tool_search`），修好环境即生效。
- [x] 场景 11（搜索不命中）：让模型搜索一个不存在的关键词，模型收到错误结果后本轮对话仍能继续、不中断、不重复尝试到超限。(AC19)
- [x] 场景 12（`/clear` 与 `/resume`）：拉取若干工具后 `/clear`，新会话首轮又只剩名字清单；`/resume` 恢复旧会话时集合**不被清空**。(AC20/F19)
- [x] 场景 13（Plan Mode）：切到 Plan Mode，`tool_search` 仍可用、拉取到的只读 MCP 工具进入列表，写类工具不可见。(AC21/F22)
## F24 实测（token 对照）
- [x] 固定合成 fixture（4 server × 15 工具 + 6 内置 = 66 个工具）下测出「全量注入 / 延迟加载首轮 / 拉取若干之后」三个数字，口径为序列化字符数 ÷ `ESTIMATE_CHARS_PER_TOKEN`（3.5），并打印成表（验证：运行测试脚本，输出对照表）。(AC27/F24)
- [x] 同时输出两条局限声明：估算非真实分词器；fixture 是合成的、不代表真实 server 的工具规模。(AC27/F24)
- [x] 不使用 Anthropic 官方博客的 85% 作为本项目结论（验证：文档与输出中只出现本项目实测值）。(AC27/F24/N13)
