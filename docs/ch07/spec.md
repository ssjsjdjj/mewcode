# MCP 客户端 Spec## 背景ch01–ch06 已经把 mewcode 砌成了一个能自主多轮干活、且有五层安全护栏的 coding agent。但**工具集是写死的 6 个内置工具**（读 / 写 / 改文件、命令执行、按模式找文件、搜内容）——想让它会用 GitHub、查数据库、调内部服务，只能改源码、重新打包，能力边界锁死在编译期。

MCP（Model Context Protocol）是一套开放标准，用统一的 JSON-RPC 协议把"提供工具的一方（server）"与"使用工具的一方（client）"解耦，社区已有大量现成 server（GitHub、Slack、SQLite、文件系统……）。ch07 给 mewcode 装上 **MCP 客户端**：启动时按配置自动发现并连接外部 server，把它们的工具包装成 mewcode 已有的工具抽象、注册进工具中心，Agent 调用时与内置工具**完全无感**，并自动复用 ch06 的权限护栏。这是从"工具集固定"到"工具生态可插拔"的一跃——给 mewcode 装上扩展坞。
## 目标- **配置驱动的自动发现**：启动时从配置声明的 server 列表自动连接、列出工具、注册进工具中心，无需改代码。
- **两种传输**：本地 server 走子进程标准输入输出管道（stdio）；远程 server 走 Streamable HTTP。
- **标准三步会话**：每个 server 一次连接经过 初始化握手 → 列出工具 → 按需调用工具（协议细节由官方 Python SDK `mcp`（`pip install mcp`）承载，不自研协议栈）。
- **无感适配**：发现到的远端工具包装成与内置工具一致的抽象，Agent 编排层与 provider 适配层均无需感知其来自远端。
- **命名空间隔离**：远端工具统一加 `mcp__<server>__<tool>` 前缀，杜绝与内置工具及多 server 间的重名冲突，并保留来源可追溯。
- **多 server 生命周期管理**：每个连接各自独立缓存与管理；单个 server 连接 / 初始化 / 列工具失败只跳过它自身，不影响其它 server、不影响启动；程序退出时统一、干净地关闭全部连接（含终止 stdio 子进程）。
- **两层配置合并**：server 列表从 **用户级** 与 **项目级** 两个配置文件读取合并，项目级覆盖用户级同名 server。
- **凭据不落盘**：配置中环境变量与请求头的值支持从宿主环境变量展开（`${VAR}`），密钥不写进配置文件。
- **复用权限**：MCP 工具天然走 ch06 的「规则 → 模式兜底 → 人在回路」链路，默认按命令执行类每次确认，自报只读（`readOnlyHint`）的按只读类放行并可并发；权限包**零改动**。
- **不破坏既有能力**：ch01–ch06 的会话、Loop、流式、缓存、规划、权限五层等行为不退化。
## 功能需求- **F1: 两层 YAML 配置加载与合并**
  从**用户级** `~/.mewcode/config.yaml` 与**项目级** `<root>/.mewcode.yaml` 两个文件读取 `mcp_servers` 段（map：key 为 server 名，value 为 server 定义）；按 server 名合并，**项目级同名 server 完整覆盖用户级**（不做字段级合并，避免半合并出畸形 server）。文件缺失视为空 `mcp_servers`；文件格式非法时**跳过该文件并 stderr 告警**，绝不致启动失败、不抛未捕获异常。`mcp_servers` 顶层不存在或为空，视为零个 MCP server，正常进 TUI。

- **F2: server 类型与必填字段**
  每个 server 定义自带 `type` 字段（**显式**：`stdio` 或 `http`），不靠字段嗅探判定类型。
  - `stdio` 类型必填 `command`（字符串）；可选 `args`（字符串数组）、`env`（字符串 map）。
  - `http` 类型必填 `url`（字符串）；可选 `headers`（字符串 map）。
  字段缺失或 `type` 非法时**跳过该 server 并 stderr 告警**，不影响其它 server 加载。

- **F3: 环境变量展开**
  `env` 与 `headers` 的**值**支持 `${VAR}` 形式从宿主环境变量取值；展开发生在配置加载阶段、不污染原始配置文件。**未定义的 `${VAR}` 展开为空串并 stderr 告警**，但不阻断该 server 启动（让 server 自行决定无凭据时是否报错）。`command` / `args` 与 server 名、工具名**不做展开**（避免命令/名字被环境间接影响产生隐性歧义）。

- **F4: stdio 传输**
  对 `stdio` 类型 server，以 `command` + `args` 启动子进程；通过子进程的标准输入输出按 JSON-RPC 帧通信（由 SDK 的 `stdio_client` + `StdioServerParameters` 完成）。`env` 与宿主进程环境合并后注入子进程（同名宿主变量被 `env` 覆盖，便于按 server 配置注入凭据）。子进程 `stderr` 透传给宿主 stderr 便于排查。子进程在 mewcode 退出时一并干净终止（关闭其 stdin → 等待 → 必要时发信号；由 SDK 的 `async with` 上下文管理器承载）。

- **F5: Streamable HTTP 传输**
  对 `http` 类型 server，以 `url` 为 endpoint 走 Streamable HTTP（由 SDK 的 `streamablehttp_client` 完成）；配置中的 `headers` 注入每次 HTTP 请求（用于 `Authorization` 等鉴权头）。**不订阅服务器推送的独立 SSE 通道**（本章只用请求-响应式工具调用，无需 server 主动推送），减少长连接维护成本。

- **F6: 标准三步会话**
  每个 server 建立后依次完成 **`session.initialize()` 握手**（交换 protocolVersion 与 capabilities）→ **`session.list_tools()` 列出工具** → 进入按需 **`session.call_tool()` 调用**阶段。整个协议层（JSON-RPC 编解码、请求/响应 id 配对、握手细节、传输细节）**由官方 Python SDK 承载**，不自研协议栈。本章只覆盖工具能力，**不订阅 / 不实现** MCP 的资源（resources）、提示词（prompts）、采样（sampling）、引导（roots）等其它能力。

- **F7: 工具适配（远端工具 ↔ 内置 Tool 抽象）**
  把 server 返回的每个远端工具包装成一个实现 mewcode `Tool` 协议的对象，注册进工具中心：
  - **名字**：`mcp__<server>__<tool>`（见 F8）。
  - **描述**：直接取远端 `description`（空则给一个含 server 名的兜底说明）。
  - **参数 schema**：把远端 `inputSchema` 转成 mewcode 的 `dict[str, Any]` 形式（透传 JSON Schema），不二次裁剪。
  - **只读性**：远端 `annotations.readOnlyHint==True` → `read_only==True`；其余（含字段缺失/非法）→ `False`（安全默认按有副作用处理）。
  - **执行**：调用时通过该 server 的会话发 `call_tool`；远端返回的 `content` 中文本块（`TextContent`）的文本按顺序拼成 mewcode `ToolResult.content`，远端 `isError==True` 映射为 `ToolResult.is_error==True`；非 text 块（image / audio / resource_link / embedded_resource 等）静默丢弃并 stderr 告警一次；调用过程中协议错误（连接断、超时、传输错）也转成 `is_error==True` 的结构化错误**回灌给模型**（不向 Agent Loop 抛 Python 异常，复用 ch04/ch05 不中断会话的契约）。Agent 与 provider 适配层不感知"该工具来自远端"。

- **F8: 工具命名空间**
  所有 MCP 工具统一以 `mcp__<server>__<tool>` 命名（`server` 与 `tool` 名按配置/远端原样保留）。命名空间用途双重：
  - **避免冲突**：同名远端工具在不同 server 互不干扰；与 6 个内置工具天然不重名。
  - **可追溯**：单看工具名能识别来源 server，便于日志、人在回路弹窗、权限规则书写。
  注册时若仍发生同名（同 server 自报多个同名工具的边界情形）则后注册者保留并 stderr 告警；若工具名经前缀拼接后含 LLM 工具名禁用字符（非 `[A-Za-z0-9_-]`），**跳过该工具并 stderr 告警**。

- **F9: 启动同步连接 + 单 server 30s 超时 + 失败隔离**
  在进入 TUI 之前**同步**对所有配置中的 server 发起连接 + 握手 + 列工具（实现并发用 `asyncio.gather` 缩短总时延）；**每个 server 的整个启动序列受 30s 超时约束**（内置不可配，用 `asyncio.wait_for`）。任一 server 的连接 / 握手 / 列工具失败或超时**只跳过它自身**：mewcode 启动不被阻断、其它 server 与内置工具集照常注册可用、stderr 给出该 server 的失败原因。所有 server 连接尝试结束后才进入 TUI；进入 TUI 时工具中心呈现的就是"内置 6 工具 + 成功连上的 server 工具"全集，Agent 在任意一轮看到的工具集稳定不变。

- **F10: 工具调用超时**
  每次 `call_tool` 复用 30s 超时（与连接超时同值，**内置不可配**，用 `asyncio.wait_for`）；超时按 F7 转成 `is_error==True` 的结构化错误回灌给模型，Agent Loop 继续。

- **F11: 退出时统一关闭**
  mewcode 正常退出（用户主动退出、致命错收尾）时，对所有已建立的会话统一调用关闭逻辑：stdio server 的子进程被干净终止（先关 stdin、给 server 自然退出窗口、必要时发信号），HTTP server 的会话用 DELETE 通知 server 释放（由 SDK 处理）。退出**不**强行等待所有连接关闭完成超过若干秒（整体兜底 5s，避免某 server 卡住拖死整个程序退出）。

- **F12: ch06 权限链路无感复用**
  MCP 工具走 ch06 现有判定链路：
  - 黑名单仅作用于内置 `bash` 命令串，对 MCP 工具不命中（`extract_target` 对未知工具返回 target=""，自动跳过）。
  - 沙箱仅作用于内置文件类工具，对 MCP 工具不适用（`extract_target` 对未知工具返回 `is_file=False`，自动跳过）。
  - 规则引擎按 `mcp__<server>__<tool>` 作为友好名匹配（`friendly_name` 对未知名原样返回）；用户可用精确名 `mcp__github__create_issue` 或带 `*` 的 `mcp__github__*` 写 allow/deny 规则。
  - 模式兜底：`read_only==True` 的 MCP 工具归 `CategoryRead`，default 下直接放行、可并发；其余归 `CategoryExec`，default 与 acceptEdits 下每次触发人在回路 Ask；bypass 下放行。
  **permission 包源码零修改**，只通过既有公共行为承载。
## 非功能需求

- N1: 失败隔离不阻塞——单 server 任意阶段（连接 / 握手 / 列工具 / 调用）失败或卡住，只跳过它自身、不阻塞 mewcode 启动、不影响其它 server 与内置工具；连接卡住时 30s 超时强制收尾，绝不死锁。
- N2: 安全默认——`readOnlyHint` 缺失或非法 → 非只读（默认走 Ask）；`${VAR}` 未定义 → 空串（不替 server 拍板）；type 非法 / 字段缺失 → 跳过该 server（不静默放行未定义 server）。
- N3: 跨协议一致——MCP 工具行为与 provider（Anthropic / OpenAI）无关；provider 适配层零修改。
- N4: ch06 权限零改动——permission 包源码零修改；MCP 工具走既有判定链路。
- N5: 不破坏 ch01–ch06——会话、Loop、流式、缓存、规划、人在回路、并发、用户取消、保序回灌等既有能力不退化。
- N6: 凭据不落盘——api_key / token 不出现在配置文件；env / headers 通过 `${VAR}` 引用宿主环境；敏感值在日志/状态栏/任何输出中不回显。
- N7: 退出干净——程序退出时不泄漏子进程、不泄漏 asyncio task、不死锁；某 server 关闭卡住不阻塞整体退出（整体退出关闭兜底超时 5s）。
- N8: 代码规范——`ruff check` / `ruff format --check` / `mypy`（可选 strict 子集）/ `pytest` 全过（本项目为 Python，遵循 CLAUDE.md 等价规范）。
## 不做的事- **MCP 资源（resources）、提示词（prompts）、采样（sampling）、引导（roots）**——本章只覆盖工具能力。
- **tools/list 变更通知 / 调用进度通知**——不订阅独立 SSE 通道（SDK 默认开，本章显式关闭或不消费），工具集快照固定在启动时。
- **健康检查 / 自动重连 / 退避**——单连接挂掉就挂掉，留待后续章节。
- **配置热加载 / 运行时增减 server**——重启 mewcode 才能应用新配置。
- **本地级 mcp_servers 配置层**——仅两层（用户级 + 项目级）。
- **mcp_servers 字段级合并**——按 server 名维度合并，同名项目级完整覆盖用户级。
- **`command` / `args` / 工具名 / server 名 的变量展开**——仅 env / headers 的值展开 `${VAR}`。
- **OAuth 完整鉴权流程**——仅支持 `headers` 直传静态 token；需要 OAuth 的 server 让用户自行预换 token 写入 headers。
- **自定义连接 / 调用超时**——30s 硬编码，不暴露配置项。
- **MCP 工具的黑名单与路径沙箱扩展**——这两层只对内置工具有意义，MCP 工具仅走规则 + 模式兜底 + 人在回路。
- **非文本内容块的回灌**——仅收集 `TextContent` 的内容块拼成 ToolResult；image / audio / resource_link / embedded_resource 等静默丢弃并 stderr 告警一次。
- **资源配额 / 速率限制 / 审计日志**——与 ch06 不做事项一致。
- **MCP server 端的实现**——mewcode 仅作 client。
## 验收标准

- AC1: 配置加载与两层合并——`~/.mewcode/config.yaml` 与 `<root>/.mewcode.yaml` 都存在时，按 server 名合并；同名 server 项目级完整覆盖用户级；任一文件缺失或非法时跳过该文件、不致启动失败、其它正常加载。（F1/N1）
- AC2: 字段校验——stdio 类型缺 command、http 类型缺 url、type 非法或缺失时，该 server 被跳过并 stderr 告警，其它 server 不受影响。（F2/N2）
- AC3: 变量展开——env / headers 的值 `${VAR}` 从宿主环境取值；未定义变量展开为空串并告警；command / args / 工具名 / server 名不展开。（F3/N2/N6）
- AC4: stdio 启动 + 子进程终止——能拉起一个 stdio MCP server 子进程，握手 + 列工具成功；env 注入生效；mewcode 退出时子进程被终止、无僵尸。（F4/F6/F11/N7）
- AC5: HTTP 连接 + 自定义 headers——能对一个 HTTP MCP server 完成握手 + 列工具；`headers` 注入到 HTTP 请求中。（F5/F6/N6）
- AC6: 工具适配与命名——同一 server 的工具列出后注册进 registry，名字符合 `mcp__<server>__<tool>`，描述非空，参数 schema 透传；调用时远端 text content 拼接为 `ToolResult.content`，远端 isError 映射到 `ToolResult.is_error`；非 text 块静默丢弃。（F6/F7/F8）
- AC7: 命名空间隔离——同名工具来自不同 server 不互相覆盖；与 6 个内置工具天然不重名；前缀拼接后含 LLM 工具名禁用字符（非 `[A-Za-z0-9_-]`）的工具被跳过并告警。（F8）
- AC8: 启动失败隔离 + 30s 超时——单 server 连接 / 握手 / 列工具失败或超时，只跳过它自身，其它 server 与内置工具集照常注册；失败原因 stderr 可见；启动总时延上界受 30s 约束（并发实现）。（F9/N1）
- AC9: 调用超时与错误回灌——`call_tool` 30s 超时或协议错误转为 `is_error==True` 的结构化错误结果回灌给模型，Agent Loop 不中断，可在后续轮调整。（F7/F10/N5）
- AC10: 退出干净——程序退出时所有 stdio 子进程被终止、HTTP 会话被关闭；关闭过程不泄漏 task、不卡死（总超时 5s 兜底）。（F11/N7）
- AC11: 权限链路自然命中——`mcp__<server>__*` 形式的 allow / deny 规则正确作用到对应 MCP 工具；未写规则时 `readOnlyHint==True` 的 MCP 工具按只读类放行并可并发，其余按命令执行类触发人在回路 Ask；bypass 模式下放行（黑名单 / 沙箱对 MCP 工具不命中，自动跳过）。（F12/N4）
- AC12: 跨协议一致——同一 MCP server 在 Anthropic 与 OpenAI 两种 provider 下行为一致；provider 适配层零 diff。（N3）
- AC13: 不破坏 ch01–ch06——既有所有测试通过；多轮连环、用户取消、流出错恢复、历史一致、缓存命中、规划按轮次注入、ch06 五层权限等行为不退化。（N5）
- AC14: 凭据不落盘——配置示例与说明均用 `${VAR}` 引用密钥；`git grep` 在配置文件中无 token 明文命中。（N6）
- AC15: 代码规范——`ruff format --check .` 无 diff；`ruff check .` 无告警；`pytest`（含 `tests/test_mcp_*.py`）通过；`pytest -m "asyncio"` 在 `tests/test_mcp_*.py` 下无悬挂 task / 死锁。（N8）

---

# 追加：工具延迟加载 + ToolSearch（2026-09-23）

> 本节追加于 ch07 主体实现并验收之后。F/N/AC 编号接续上文（上文止于 F12 / N8 / AC15）。上文所有条目继续有效，本条既不修改也不废止其中任何一条。

## 背景

ch07 主体让 MCP 工具「进得来」，但走的是**全量注入**：启动时对每个 server 并发 `list_tools`，把每个工具适配后登记，此后**每一轮**都把这批工具的完整 schema 写进请求的 `tools` 数组。

用户配 4 个 server、每个 15~20 个工具，加内置 6 个，工具定义规模可达 80 个。这带来两个后果：

1. **上下文被预先吃掉一块**：单个工具的完整 schema（名称 + 描述 + 参数 JSON Schema）约 100~300 token，80 个即约 8k~24k token，每轮常驻、还没开始干活就已占位。
2. **干扰模型的选择质量**：工具名高度相似时（`query_prometheus` / `query_prometheus_histogram` / `query_loki_logs` / `query_loki_stats`），模型需要在近义项之间做决策。

> **关于 85% 这个数字**：Anthropic 工程博客 *Advanced Tool Use* 公布了「50+ 工具场景启用延迟加载后 token 开销降低约 85%、Opus 4 工具选择准确率 49%→74%」。**该数据来自该博客，不是本项目实测结果，不作为本项目的结论或宣传口径。** 本节的 F-numbered 目标（G5 / F24）是产出一份**属于本项目自己的、可复现的**对照实测。

本节追加「工具延迟加载」：MCP 工具默认**不注入**完整 schema，改为只在补充消息（system-reminder）里向模型暴露**名字**；模型需要时调用新增的内置工具 `tool_search` 拉取完整定义，该工具**从下一轮起转为常驻**。

分界线是「数量可不可控」：内置工具由代码写死、数量可控，且 `read_file` / `bash` 这类几乎每轮都用，藏起来只会让模型多绕一次 `tool_search`——省下的 token 还不够来回一趟的开销，故**一律常驻**；MCP 工具数量由用户配置决定、加一个 server 就可能多出几十个，且大部分工具单次会话根本用不上，故**一律延迟**。

## 目标

- **G1**：MCP 工具默认不注入完整 schema，改为只向模型暴露名字，按需拉取。
- **G2**：新增内置工具 `tool_search`，支持两种拉取方式——按完整工具名精确拉取、按关键词搜索（带结果上限）。
- **G3**：被拉取过的工具在**当前会话内**转为常驻，后续每轮正常注入，模型不需要反复拉取。
- **G4**：内置工具一律常驻，不受延迟机制影响；**未配置任何 MCP server 时，请求内容与工具集与本追加前完全一致**。
- **G5**：产出一份可复现的 token 对照实测，量化延迟加载前后「工具定义」这一项的开销，并明确标注其口径与局限。

## 功能需求

- **F13: 延迟属性的声明**
  mewcode 的工具抽象新增一个「是否可延迟」的声明位。**内置 6 个工具声明为不可延迟**；**MCP 工具（`mcp__<server>__<tool>`）声明为可延迟**。该属性由工具自身声明，**不由注册中心按名字前缀硬编码推断**——名字前缀是约定，不是机制，靠前缀判断会让「将来非 MCP 来源的工具（如后续章节的能力包）」无法复用本机制。

- **F14: 每轮工具列表的构成**
  Agent 每轮构建请求的 `tools` 时，对注册中心里的每个工具三选一：
  - **不可延迟** → 始终注入完整定义。
  - **可延迟且本会话尚未被拉取** → **不注入**，只出现在 F15 的名字清单里。
  - **可延迟且本会话已被拉取** → 注入完整定义。
  三种情形下，被注入工具的相对顺序均沿用注册顺序（稳定、可复现）。

- **F15: 延迟工具名字清单**
  当且仅当存在「可延迟且尚未被拉取」的工具时，每轮请求附加一条补充消息：按 **server 分组**列出这些工具的完整名字（`mcp__<server>__<tool>`），并说明可用 `tool_search` 拉取。
  清单**不设条数上限**——截断会让被截掉的工具对模型**永久不可见**，那比多花一点 token 严重得多。没有任何此类工具时，该补充消息**不下发**（与追加前一致）。

- **F16: tool_search 的注册时机**
  `tool_search` 是**内置工具**，声明为**只读**（它只读注册中心，不产生任何外部副作用）。
  **它只在「存在至少一个可延迟工具」时才注册进注册中心**。未配置 MCP server、或所有 server 都连接失败时，注册中心与本追加前**完全一致**（仍为 6 个内置工具），既有测试与既有行为零影响。
  它是**普通已注册工具**：模型调用它不会落入「未知工具」计数（沿用 ch04 的 `MAX_UNKNOWN_RUN` 护栏语义）。

- **F17: select 精确拉取**
  入参以 `select:` 开头时，取其后内容作为**完整工具名**精确查找。
  - **命中**：返回该工具的完整定义，并标记为「已发现」。
  - **未命中**：返回 `is_error` 的结构化错误结果，提示可改用关键词搜索。错误**回灌给模型**，不抛异常、不中断 Loop（沿用 ch07 F7 的既有契约）。

- **F18: 关键词搜索 + Top-N 上限**
  入参**非** `select:` 形式时，视为关键词查询，在「可延迟且尚未被拉取」的工具的**名字与描述**中匹配。
  - **排序**：名字命中优先于描述命中；同档内按注册顺序。
  - **上限**：**最多返回 5 个**完整定义，全部标记为「已发现」。
  - **截断**：命中数超过 5 个时，在结果中说明被截断以及总命中数，提示可缩小关键词。
  - **零命中**：返回 `is_error` 的结构化错误结果，提示换用更短的关键词或 `select:<完整工具名>`。
  上限的意义在于守住延迟加载的初衷：关键词过宽（如 `get`）时若不设限，一次就能把几十个 schema 拉回上下文，省 token 的效果被吃回去。

- **F19: 已发现状态的作用域**
  已发现集合是**会话内存态**，**不写入**会话存档文件：
  - 进程重启 → 清空（全部可延迟工具退回延迟态）。
  - `/clear` 开新会话 → 清空。
  - `/resume` 恢复旧会话 → **不恢复**已发现集合（被延迟的工具退回延迟态，模型需重新拉取）。
  理由：已发现集合是「模型此刻的注意力状态」，不是会话的持久事实；把它写进存档会让 ch09 的存档格式与恢复逻辑为一条缓存付出兼容成本。

- **F20: 幂等**
  对**已发现**的工具再次 select、或再次被关键词搜索命中，返回完整定义且**不报错、不重复登记、不影响顺序**。

- **F21: 延迟不改变其它任何链路**
  延迟**只**改变两件事：哪些工具的完整定义进不进本轮请求、本轮结果列表里是否多一个 `tool_search`。以下既有行为**逐条不变**：
  - 工具执行、超时、错误回灌、并发分批；
  - ch06 五层权限判定（已发现的 MCP 工具照常走原链路：规则 → 模式兜底 → 人在回路；`readOnlyHint` 语义不变）；
  - 未发现的 MCP 工具因为**不在**工具列表里，模型不会调用它们——这是延迟的自然结果，不是额外的拦截；
  - ch08 上下文管理对 `tool_defs` 的消费方式不变（它拿到的就是本轮实际要注入的那一份）。

- **F22: Plan Mode 下的叠加**
  Plan Mode 下请求的 `tools` 仍为「只读子集」；延迟机制在只读子集**之上**再过滤一层——只读且尚未被拉取的 MCP 工具同样只出现在名字清单里。`tool_search` 自身只读，Plan Mode 下**正常可用**（否则 Plan Mode 下将无法发现任何 MCP 工具）。

- **F23: 未配置 MCP server 时的等价性**
  未配置任何 MCP server（或全部连接失败）时：注册中心仍是 6 个内置工具、请求的 `tools` 与补充消息与本追加前**逐字节一致**。这是 G4 的可观测形式，也是 N10「不破坏既有能力」的核心断言。

- **F24: 可复现的 token 对照实测**
  产出一份**确定性**的对照实测：用一份固定的**合成**工具集（4 个虚拟 server × 15 个工具 + 6 个内置，共 66 个工具——数量贴近「配置了 4 个 server」的真实场景），在同一进程内分别统计：
  - **延迟加载前**：全部 MCP 工具完整定义注入时的工具定义开销；
  - **延迟加载后**：首轮（只有内置定义 + 名字清单）与拉取若干工具后的开销。
  **计数口径**：与 ch08 压缩阈值使用**同一个**换算系数，即按序列化字符数除以 `ESTIMATE_CHARS_PER_TOKEN`（3.5）估算 token——保证这个数与 Agent 自身用于压缩决策的 token 量纲一致。
  **必须写明**：这是**估算值**（非真实 tokenizer），且工具集是**合成 fixture**（非真实外部 server 实测）；两项局限都要在产出物中原样标注，不得省略。

## 非功能需求

- **N9: 每轮构造是纯内存操作**——名字清单与本轮 `tools` 的构造不引入任何 I/O、不发起网络请求、不读磁盘；不随轮次累积计算。
- **N10: 不破坏 ch01–ch10**——既有全部测试通过；未配置 MCP server 时工具集、请求 `tools`、补充消息与本追加前完全一致；ch10 的 `/status`「可用工具数量」在没有 MCP 时仍报 6。
- **N11: 确定性**——给定同一注册集与同一已发现集，任何一轮生成的 `tools` 顺序与名字清单内容**逐字节可复现**（排序规则明确、不依赖字典/set 迭代顺序）。
- **N12: 代码规范**——`ruff format --check .` 无 diff；`ruff check .` 无告警；`pytest` 全过（含既有 `tests/test_mcp_*.py` 与 `tests/agent/`）。
- **N13: 跨协议一致**——延迟机制完全在客户端与 Agent 编排层实现，**不依赖任何厂商专有字段**（不使用 Anthropic 原生的 `defer_loading`）；Anthropic 与 OpenAI 两个 provider 行为一致，provider 适配层零修改。

## 不做的事

- **已发现状态的持久化**——不写会话存档、不跨重启、不跨 `/resume`（见 F19）。
- **语义/向量式工具检索**——只做名字与描述的字面匹配，不引入 embedding、不做相关度排序模型。
- **Anthropic 原生 `defer_loading` 字段**——厂商专有，智谱 GLM / OpenAI 等会静默忽略；客户端自实现是唯一跨厂商方案（见 N13）。
- **关键词搜索的「摘要预览」两段式**——关键词命中直接回完整 schema，不做「先回名字、再 select」的中间态。
- **内置工具的按需延迟**——内置一律常驻，不提供「把内置也延迟」的开关。
- **延迟列表的自动淘汰 / 过期**——已发现的工具在会话内不再退回延迟态。
- **运行时工具集变更**——不消费 `tools/list` 变更通知，工具集快照固定在启动时（沿用 ch07 不做事项）。
- **把博客的 85% / 49%→74% 当作本项目结论**——那两个数只作为「这个方向有价值」的旁证引用，本项目的口径以 F24 的实测为准。
- **MCP 工具名清单的分页 / 折叠**——清单不设上限也不分页（见 F15）。

## 验收标准

- **AC16: 延迟属性与列表构成**——配 1 个提供 N 个工具的 MCP server 时，首轮请求的 `tools` 只含内置工具（MCP 工具一个都不含）；N 个 MCP 工具的名字全部出现在补充消息里。（F13/F14/F15）
- **AC17: 名字清单形态**——清单按 server 分组、含完整 `mcp__<server>__<tool>` 名字、不设条数上限；未配置 MCP server 时**不下发**该补充消息。（F15/F23）
- **AC18: select 精确拉取**——`select:<完整名>` 命中后，该工具**从下一轮起**出现在请求的 `tools` 里；未命中时返回 `is_error` 结构化结果且 Loop 不中断。（F17）
- **AC19: 关键词搜索 Top-N**——命中按「名字优先于描述」排序、最多 5 条、超限时说明被截断及总数；零命中返回 `is_error` 结构化结果。（F18）
- **AC20: 已发现状态的作用域**——`/clear` 后回到延迟态；`/resume` 恢复后仍是延迟态；重启后仍是延迟态；会话存档文件内**不含**已发现集合。（F19）
- **AC21: 幂等**——对同一工具重复 select 或重复被搜索命中，返回完整定义、不报错、注册集与顺序不变。（F20）
- **AC22: 权限与执行无回归**——已发现的 MCP 工具仍走 ch06 五层判定（`readOnlyHint==True` 按只读放行并可并发、其余触发人在回路）；调用 30s 超时与协议错误仍转结构化结果回灌。（F21）
- **AC23: Plan Mode 叠加**——Plan Mode 下请求的 `tools` 只含「只读且已发现」的工具；`tool_search` 在 Plan Mode 下可用。（F22）
- **AC24: 无 MCP server 时的等价性**——未配置 MCP server 时，注册集为 6 个内置工具、请求 `tools` 顺序与内容、补充消息与本追加前逐字节一致；既有多轮／取消／压缩／权限等测试全绿。（F23/N10）
- **AC25: token 实测可复现**——同一 fixture 重复运行得到**相同**数字；产出物同时标注「估算口径（字符数 ÷ 3.5）」与「合成 fixture，非真实 server 实测」两项局限。（F24）
- **AC26: 跨协议一致**——同一延迟行为在 Anthropic 与 OpenAI 两个 provider 下一致，provider 适配层零 diff。（N13）
- **AC27: 代码规范**——`ruff format --check .` 无 diff、`ruff check .` 无告警、`pytest` 全过；构造顺序断言在多次运行下稳定（不依赖 set/dict 迭代顺序）。（N11/N12）
