# 🐱 MewCode

一个 Claude Code 风格的终端 AI 编码助手：在终端里和模型多轮对话，让它自主读代码、改文件、跑命令。

从零实现，不依赖 LangChain / LlamaIndex 之类的框架——Agent Loop、上下文压缩、权限护栏、MCP 客户端都是自己写的。每章先写四份设计文档（`spec` → `plan` → `task` → `checklist`）再落地代码，文档在 `docs/` 下。

需要 Python ≥ 3.12。

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 配置

启动时读取**当前工作目录**下的 `.mewcode/config.yaml`，模板见 `.mewcode/config.yaml.example`。

```yaml
providers:
  - name: my-claude
    protocol: anthropic          # anthropic | openai
    model: claude-sonnet-5
    base_url: https://api.anthropic.com   # 可省略，按协议取默认端点
    api_key: sk-ant-xxxx
    thinking: true               # 仅 anthropic 生效
    context_window: 200000       # 可省略，按协议取默认值
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 供应商标识名 |
| `protocol` | ✅ | `anthropic` 或 `openai` |
| `model` | ✅ | 模型名 |
| `base_url` | ❌ | 自定义端点，缺省用协议默认端点 |
| `api_key` | ✅ | API 密钥（保密） |
| `thinking` | ❌ | 是否开启扩展思考，默认 `false`（仅 anthropic 生效） |
| `context_window` | ❌ | 上下文窗口（token），缺省按协议默认 |

默认端点：

| 协议 | 默认 base_url | 请求路径 |
|------|--------------|---------|
| anthropic | `https://api.anthropic.com` | `{base_url}/v1/messages` |
| openai | `https://api.openai.com/v1` | `{base_url}/chat/completions` |

配置多个 provider 时，启动后出现方向键选择列表；只配一个时直接进入对话。

### 项目指令

按优先级扫描三层 `MEWCODE.md`，命中即加载，按序拼进系统提示：

1. `<项目根>/MEWCODE.md` —— 项目级
2. `<项目根>/.mewcode/MEWCODE.md` —— 项目配置级
3. `~/.mewcode/MEWCODE.md` —— 用户级

支持 `@include` 引用其他文件（嵌套上限 5 层，路径不可逃逸出所属根）。

### Skill 与 Hook

两者都放在项目级（`<项目根>/.mewcode/`）或用户级（`~/.mewcode/`），项目级优先。

**Skill** —— 一个目录一个技能，`SKILL.md` 用 YAML frontmatter 声明元信息、正文写 SOP：

```markdown
---
name: commit
description: 分析 git diff 并生成规范的提交
allowed_tools: [bash, read_file, grep]
mode: inline          # inline 注入主对话 / fork 起隔离子 Agent
---

（SOP 正文，支持 $ARGUMENTS 占位符）
```

放进 `.mewcode/skills/<name>/` 即自动注册成 `/<name>` 命令。目录里还可以放 `tool.json`
声明专属脚本工具（脚本入参走 stdin 的 JSON、stdout 作为结果）。用 `load_skill` 工具
或自然语言触发时，完整 SOP 会钉进当前会话的上下文。

**Hook** —— `.mewcode/hooks.yaml` 里用「事件 + 条件 + 动作」声明自动化：

```yaml
hooks:
  - name: block-writes
    event: PreToolUse                    # 11 个生命周期时刻之一
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
    action:
      type: shell
      command: "echo 不允许写文件 >&2; exit 2"   # exit 2 = 拦截，stderr 作为原因
```

条件复用权限系统的四种匹配语法（`exact` / `glob` / `regex` / `not`，字段路径用 `.` 取嵌套）。
动作有 `shell` / `prompt` / `http` / `subagent` 四种；`only_once` 让规则每会话只跑一次，
`async` 让它不阻塞主流程（拦截类事件不允许 async）。所有配置与执行错误只记 stderr、
不阻断 Agent。输入 `/hooks` 查看当前生效的规则。

## 使用

```bash
python -m mewcode
```

| 操作 | 方法 |
|------|------|
| 发送消息 | 输入文字后按 **Enter** |
| 换行（多行输入） | **Alt+Enter** |
| 退出 | 输入 **/exit** 或按 **Ctrl+C** |

### 斜杠命令

| 命令 | 作用 |
|------|------|
| `/status` | 显示模式 / 用量 / 工具等状态 |
| `/permission` | 显示当前权限模式 |
| `/plan` | 切换到计划模式（只读工具） |
| `/do` | 按计划开始执行 |
| `/compact` | 手动触发上下文压缩 |
| `/clear` | 清空当前会话，开启新会话 |
| `/resume` | 恢复历史会话 |
| `/session` | 显示当前会话信息 |
| `/memory` | 列出已加载的记忆文件 |
| `/skill` | 列出已加载的 Skill |
| `/hooks` | 列出已加载的 hook |
| `/help` | 查看可用命令列表 |
| `/exit` | 关闭 MewCode |

此外，每个已加载的 Skill 会自动注册成一条 `/<skill-name>` 命令（见下）。

## 已实现的能力

**ReAct Agent Loop** —— 模型自主多轮调用工具，直到任务结束。每个工具调用在真正执行前穿过五层权限护栏。

**双协议 Provider** —— 统一 `Provider` 接口 + 工厂，Anthropic 与 OpenAI 协议（含 DeepSeek 等兼容端点）自由切换，流式输出。

**内置工具** —— `ReadFile` / `WriteFile` / `EditFile` / `Bash` / `Glob` / `Grep`；另有工具延迟加载（`tool_search`），按需把工具定义注入上下文。

**五层权限护栏** —— 黑名单 → 沙箱 → 规则 → 模式兜底 → 人在回路。规则支持四种匹配语法：`Bash(=git status)` 精确、`Bash(~^npm (install|test)$)` 正则、`Bash(!~^rm)` 反向、`Bash(git *)` glob。支持权限模式的切换与持久化，`plan` 模式下只放行只读工具。

**MCP 客户端** —— 同时支持 stdio 与 streamable HTTP 两种传输，远端工具适配进本地工具中心后对上层完全透明；单个 server 连接失败只跳过自身，不影响其他 server。

**上下文管理** —— 基于真实 usage 锚点 + 字符增量的 token 估算；接近窗口上限时自动压缩，也可 `/compact` 手动触发；压缩失败有紧急恢复路径，不会把对话写坏。

**会话持久化** —— 每次启动生成 `<YYYYMMDD-HHMMSS-xxxx>` 会话目录，对话以 JSONL 实时追加写入，`/resume` 可恢复历史；超过 30 天的会话自动清理。

**长期记忆** —— 由模型从对话中自动提取，按项目级 / 用户级两级存放，索引经 `MEMORY.md` 注入系统提示。

**Skill 技能包** —— 把可复用的 AI 操作写成 `SKILL.md` 目录（YAML frontmatter + SOP 正文），放进 `.mewcode/skills/` 即自动注册成 `/<name>` 命令。两阶段加载：启动时只把名字与描述注入系统提示，模型用 `load_skill` 按需把完整 SOP 钉进上下文，注意力不被撑爆。支持 `inline`（注入主对话）与 `fork`（起隔离的子 Agent 跑完再回流）两种执行模式、`tool.json` 声明专属脚本工具、以及从 URL 安装第三方 Skill 包。内置 `commit` / `review` / `test` 三个。

**Hook 生命周期挂钩** —— 在 `.mewcode/hooks.yaml` 里用「事件 + 条件 + 动作」声明自动化，11 个生命周期时刻可选，动作为 shell / 提示词注入 / HTTP / 子 Agent。`PreToolUse` 与 `UserPromptSubmit` 可拦截（shell 用 `exit 2`、HTTP 用 `{"decision":"block"}` 表达），拦截原因回灌给模型或提示用户重编辑。条件复用权限系统的四种匹配语法。所有加载与执行错误只记日志、不阻断 Agent。用 `/hooks` 查看当前生效的规则。

## 路线图

`docs/` 下已写好设计文档、代码待补的章节：

| 章节 | 主题 |
|------|------|
| ch13 | SubAgent 机制 |
| ch14 | Worktree 隔离 |
| ch15 | Agent Team 多智能体协作 |

## 开发

```bash
python -m pytest tests/ -q     # 649 passed, 1 skipped
python -m ruff check src tests
```

## 目录结构

```
src/mewcode/
├── agent/          # ReAct 循环编排 + 权限接入 + hook 埋点
├── llm/            # 统一 Provider 接口 + anthropic/openai 实现
├── tool/           # 内置工具 + 工具中心 + 延迟加载 + Skill 工具
├── permission/     # 五层权限护栏 + 四种匹配器（exact/glob/regex/not）
├── hook/           # 生命周期事件、规则加载、动作执行
├── skills/         # SKILL.md 解析、三层 Catalog、执行器、内置技能
├── mcp/            # MCP 客户端、连接管理、远端工具适配
├── compact/        # token 估算 + 上下文压缩 + 紧急恢复
├── session/        # 会话 JSONL 存档、恢复、清理
├── memory/         # 长期记忆提取与召回
├── instructions/   # 三层 MEWCODE.md 指令加载
├── prompt/         # 系统提示词组装（环境/模块/提醒/Skill 两阶段）
├── command/        # 斜杠命令注册与分发
├── config/         # 配置加载与校验
├── conversation.py # 对话数据结构
└── tui/            # textual 界面

docs/chNN/          # 每章 spec / plan / task / checklist 四份文档
tests/              # 与 src 同构的测试
```
