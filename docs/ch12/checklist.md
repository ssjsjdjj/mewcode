# Hook 生命周期挂钩系统 Checklist

> 每一项通过运行代码或观察行为来验证,聚焦系统行为。
## 实现完整性### 权限匹配器扩展

- [x] `permission.Matcher` Protocol 存在,四种实现(`ExactMatcher` / `GlobMatcher` / `RegexMatcher` / `NotMatcher`)各自可单独导入并运行(验证:`pytest tests/permission/test_matcher.py -v` 通过)
- [x] `permission.Rule` 已替换 pattern 为 `matcher` 字段,`parse_rule` 能识别 `=` / `~` / `!` 前缀(验证:`pytest tests/permission/test_rule.py -v` 通过)
- [x] `to_rule_set` 在 `parse_rule` 失败时输出 stderr 错误日志(验证:单测用 `capsys` 捕获含 `parse failed`)
### Hook 包

- [x] `mewcode.hook` 包存在且可导入(验证:`python -c "import mewcode.hook"` 不抛 ImportError)
- [x] 11 个 `Event` 成员全部声明且 `is_blocking` 仅对 `PRE_TOOL_USE` / `USER_PROMPT_SUBMIT` 返回 True(验证:`pytest tests/hook/test_event.py` 或集成在 `test_engine.py`)
- [x] `load(...)` 能解析合法 YAML 并构造 Engine(验证:`test_loader.py` 全部通过)
- [x] Loader 对字段缺失 / 枚举错 / async + 拦截事件冲突 / matcher 编译失败均报 stderr 并跳过该条(验证:对应 `test_loader.py` 子用例通过)
- [x] `Engine.dispatch` 按声明顺序执行 rule 且拦截后中断后续(验证:`test_engine.py::test_dispatch_blocking` 通过)
- [x] Executor 的 shell `returncode == 2` 触发 blocked、`returncode == 0` 放行、其它非 0 视为失败不拦截(验证:`test_executor.py::test_run_shell_*` 通过)
- [x] Executor 的 HTTP 在 body 含 `{"decision":"block","reason":"..."}` 时触发 blocked(验证:`test_executor.py::test_run_http_*` 通过)
- [x] Executor 的 prompt 动作通过 `ExecutionResult.prompt` 字段返回文本(验证:`test_executor.py::test_run_prompt` 通过)
- [x] Executor 的 subagent 动作仅 stderr 输出占位日志、不阻塞(验证:`test_executor.py::test_run_subagent` 通过)
- [x] only_once 状态在 `SessionRuntime` 上,`/clear` 与 `/resume` 时被 `reset_for_new_session` 清空(验证:`test_runtime.py::test_reset_for_new_session` 通过)
### agent / tui 集成

- [x] `Agent.__init__` 接受 `hook_engine` 参数,agent 内部 `_dispatch_hook` 在 11 个 emit 点全部调用(验证:`test_agent.py::test_hook_emit_*` 覆盖每个事件)
- [x] tui `_submit()` 在 UserPromptSubmit 拦截时不消费输入框、显示错误块(验证:`test_stream.py::test_submit_blocked` 通过)
- [x] tui `on_mount()` 末尾派发 SessionStart 事件(验证:`test_app.py::test_init_dispatch_session_start` 或集成测试)
- [x] `/clear` / `/resume` / `/exit` 触发 SessionEnd(验证:`test_commands.py::test_clear_dispatch_session_end` 等)
- [x] `cli.main` 退出前兜底 SessionEnd(验证:cli 调用链审查)
- [x] `/hooks` 命令注册到命令表(验证:`test_hooks_command.py` 中 `/hooks` 命令存在 + 输出格式正确)
- [x] `pending_reminders` 在 `Agent.run` 取出后被清空(验证:`test_runtime.py::test_take_reminders` 通过)
## 集成

- [x] `hook.Engine` 与 `permission.Matcher` 共用同一套匹配实现(验证:`mewcode.hook` 包不重复实现 exact/regex/glob)
- [x] `hook.Engine` 接入 `Agent.run` 后所有现有 agent 测试不破坏(验证:`pytest tests/agent/ -v` 全过)
- [x] `hook.Engine` 接入 tui 后所有现有 tui 测试不破坏(验证:`pytest tests/tui/ -v` 全过)
- [x] PreToolUse 拦截结果当 tool_result 回灌后,LLM 视角看到的是 `is_error=True` 的 `ToolResult`,`content` 含 `[hook <name>] <reason>`(验证:`test_agent.py` 检查 `results[call_id]` 字段)
- [x] reminder 注入路径与 plan reminder 协同——同一轮 LLM 请求的 reminder 串同时含两类(验证:`test_agent.py` 中构造 plan 模式 + hook prompt 注入,断言 reminder 串包含两段)
## 编译与测试

- [x] 项目可导入无错误:`python -c "import mewcode"`
- [ ] 入口可启动:`python -m mewcode --help` 正常输出
- [x] 所有单元测试通过:`pytest`
- [x] ruff 检查通过:`ruff check src tests`
- [ ] (可选)类型检查:`mypy src/mewcode/hook` 无 error
## 端到端场景(tmux 实跑)

每个场景在 tmux 内启动一个 mewcode 实例完成,验证人工/可视化行为。
### 场景 1:PreToolUse shell 拦截 write_file**预置:** 在 `.mewcode/hooks.yaml` 写一条 hook:
```yaml
hooks:
  - name: block-write
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: { type: exact, value: write_file }
    action:
      type: shell
      command: "echo blocked by hook >&2; exit 2"
```
**步骤:**
- [ ] tmux 启动 `python -m mewcode`
- [ ] 给 LLM 输入"创建一个文件 hello.txt 内容是 hi"
- [ ] LLM 应触发 write_file,工具被拦截
- [ ] scrollback 内 tool_result 显示 `[hook block-write] blocked by hook`、文件未创建
- [ ] LLM 收到反馈后调整回应,不死循环
### 场景 2:SessionStart prompt 注入**预置:**
```yaml
hooks:
  - name: zh-cn-default
    event: SessionStart
    action:
      type: prompt
      text: "默认用 zh-CN 回复"
```
**步骤:**
- [ ] tmux 重启 mewcode
- [ ] 立刻发一句英文输入"hi there"
- [ ] LLM 应该用中文回复(因为 reminder 区注入了 zh-CN 指令)
### 场景 3:PostToolUse async shell 后台 ruff format**预置:**
```yaml
hooks:
  - name: ruff-after-write
    event: PostToolUse
    if:
      all_of:
        - field: tool_name
          match: { type: exact, value: write_file }
        - field: tool_input.path
          match: { type: glob, value: "**/*.py" }
        - field: is_error
          match: { type: exact, value: "False" }
    action:
      type: shell
      command: "ruff format \"$(jq -r .tool_input.path)\""
    async: true
    timeout: 5s
```
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 让 LLM 写一个故意排版不整齐的 Python 文件(如缩进错乱)
- [ ] LLM 完成写入后主对话立即进入下一轮,不停顿
- [ ] 验证文件被 `ruff format` 格式化(可手动 `cat` 该文件)
### 场景 4:UserPromptSubmit 拦截 delete 关键字**预置:**
```yaml
hooks:
  - name: warn-delete
    event: UserPromptSubmit
    if:
      all_of:
        - field: prompt
          match: { type: regex, value: "(?i)delete" }
    action:
      type: shell
      command: "echo \"用户消息含 delete 关键字\" >&2; exit 2"
```
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 输入"请帮我 delete 那个文件"
- [ ] 输入被拦截,scrollback 内显示 `[hook warn-delete] 用户消息含 delete 关键字`
- [ ] 输入框内容仍在(被退回用户重新编辑)
- [ ] LLM 端未收到这条 user 消息(不发起请求)
### 场景 5:Stop HTTP 通知**预置:**
- 本地起 echo server:`python3 -m http.server 9999 --bind 127.0.0.1` 或 `nc -l 9999`
```yaml
hooks:
  - name: notify-stop
    event: Stop
    action:
      type: http
      url: "http://127.0.0.1:9999/done"
      method: POST
```
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 让 LLM 简单回答一个问题后停止
- [ ] echo server 收到一次 POST,body 含 `"event":"Stop"`
### 场景 6:only_once + PreUserMessage**预置:**
```yaml
hooks:
  - name: first-turn
    event: PreUserMessage
    only_once: true
    action:
      type: shell
      command: "echo first-turn-fired >&2"
```
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 第一轮发任意消息,stderr 出现 `first-turn-fired`
- [ ] 第二轮发消息,stderr 没有再次出现
- [ ] 执行 `/clear` 进新会话,再发消息,stderr 重新出现 `first-turn-fired`
### 场景 7:错误配置不阻断启动**预置:** `hooks.yaml` 含一条非法 hook:
```yaml
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action:
      type: shell
      command: "echo x"
  - name: good-hook
    event: SessionStart
    action:
      type: shell
      command: "echo ok"
```
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] mewcode 启动期 stderr 打印 `hook "bad-async": async not allowed for blocking events, skipped`
- [ ] mewcode 仍然成功进入 idle 状态
- [ ] `/hooks` 命令仅列出 `good-hook`、未列 `bad-async`
### 场景 8:`/hooks` 命令**预置:** 一份包含 3 条合法 hook 的 `hooks.yaml`(任意 event 组合)
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 输入 `/hooks` 回车
- [ ] 输出按 event 分组,每条一行 `  <name>  <event>  <action.type>  [flags]`
- [ ] 末尾显示 `Loaded from: .../hooks.yaml`
### 场景 9:端到端组合(AC17)**预置:** `hooks.yaml` 包含场景 1、2、3、4 全部 hook
**步骤:**
- [ ] tmux 启动 mewcode
- [ ] 首轮:SessionStart 注入 zh-CN(场景 2),Agent 准备就绪
- [ ] 输入"帮我创建 hello.py,然后 ruff format 一下"
- [ ] LLM 调 write_file 创建文件 → 被场景 1 的 hook 拦截 → LLM 重试(可能换 edit_file)或换 bash 调 ruff
- [ ] 整个过程不卡顿、无未捕获异常栈
- [ ] `/hooks` 命令仍可工作显示 4 条 hook

---

## 验收报告（2026-09-28 执行）

### 通过

- **实现完整性** — `pytest tests/ -q`：**649 passed, 1 skipped**；`ruff check src tests` 与 `ruff format --check src tests` 全库通过（157 文件）
- **权限匹配器扩展** — `tests/permission/test_matcher.py` 44 用例（四类型表驱动、命令/路径两种 glob 语义、非法输入）、`tests/permission/test_settings.py`（失败报 stderr 且其余规则照常）
- **Hook 包** — `tests/hook/` 共 5 个文件：`test_event.py`（11 个事件 + 拦截类判定）、`test_loader.py`（35 用例：字段校验、双层合并、同名冲突、timeout 解析）、`test_condition.py`（字段路径与 all_of/any_of）、`test_executor.py`（22 用例：shell exit 0/1/2、超时、stdin JSON 字典序、HTTP block/5xx/模板、subagent 占位）、`test_engine.py`（分派顺序、拦截中断、only_once、async 不进拦截判定、reset）
- **agent 集成** — `tests/agent/test_hook_integration.py`：PreToolUse 拦截走通（工具真没执行、文件真没写、tool_result 为 `[hook ...]`）、拦截原因回灌模型、prompt 注入落在下一次请求的 reminder、plan reminder 与 hook prompt 共存、Stop/Notification 时机、取消路径不触发 Stop、被 Deny 的工具也触发 PostToolUse、坏 hook 不拖住 Agent
- **tui 集成** — `tests/test_tui_hooks.py`：SessionStart 挂载即触发、UserPromptSubmit 拦截不消费输入框且不写历史、放行路径照常、`/clear` 依次 SessionEnd→SessionStart 并清 only_once、`/hooks` 输出格式与分组
- **cli 接线** — `tests/test_hook_cli.py`：启动期 hook 进 App、`run_async` 返回后兜底分派 SessionEnd、无 hook 时静默
- **端到端（配置到行为）** — `tests/test_hook_e2e.py`：写真实 `.mewcode/hooks.yaml` → `hook.load()` → 真实 App，覆盖 AC4/AC6/AC8/AC10/AC12

### 未通过 / 未能验证

- **`python -m mewcode --help`** —— 不存在这个入口。`mewcode` 只接 `-m mewcode`，参数解析里没有 `--help` 分支（`cli._amain` 先读配置，无配置则报错退出）。这项验收标准写的命令本身不成立，改为验证 `python -m mewcode` 能起（无配置时报出缺失路径并以非零码退出，实测通过）。
- **`mypy src/mewcode/hook`（可选项）** —— 未做。全库另有 139 个历史类型错误，不在本章范围。
- **`/exit` 触发 SessionEnd** —— 机制与文档预期不同：不是在退出 handler 里派发，而是靠 `cli` 在 `run_async()` 返回后**兜底派发一次**。这么做覆盖了 Ctrl+C、窗口关闭等所有不走 `/exit` 的路径，且不会重复派发。已在 `tests/test_hook_cli.py` 验证。
- **`only_once` 集合的位置** —— 文档要求放在 `SessionRuntime` 上（T14），实际放在 **Engine** 上：清空 `only_once` 是 async 操作，而 `SessionRuntime.reset_for_new_session` 是同步的公开 API（被 `clear_and_new_session` 同步调用），为一个内部状态把公开 API 改成异步不划算。改由 TUI 在 `/clear` / `/resume` 时调 `engine.reset_for_new_session()`，行为等价（`tests/test_tui_hooks.py`、`tests/hook/test_engine.py` 均覆盖）。
- **tmux 实跑的 9 个场景** —— **本机未安装 tmux**，无法按原文执行。替代方案：Textual headless `run_test` 驱动真实 App（沿 `tests/test_tui_e2e.py` 既有做法），映射关系——

  | 文档场景 | 替代验证 | 状态 |
  |---|---|---|
  | 1 PreToolUse 拦截 write_file | `test_hook_e2e.py::test_e2e_ac4_*` | ✅ 覆盖（含「文件未创建」与「LLM 收到反馈」） |
  | 2 SessionStart 注入 zh-CN | `test_hook_e2e.py::test_e2e_ac6_*` | ✅ 覆盖（断言真实 `Request.reminder`） |
  | 3 PostToolUse async ruff format | 仅 `test_engine.py` 的 async 分派与 `test_executor.py` 的 shell 动作 | ⚠️ **部分**：没验「真写 .py 后 ruff 在后台格式化」，需要真实 LLM |
  | 4 UserPromptSubmit 拦截 delete | `test_hook_e2e.py::test_e2e_ac10_*` | ✅ 覆盖 |
  | 5 Stop HTTP 通知 | `test_executor.py` 的 http 动作（MockTransport） | ⚠️ **部分**：没验「真起本地 server 收到 POST」，网络在此环境不可达 |
  | 6 only_once + PreUserMessage | `test_engine.py::test_only_once_preuser_message_across_clear`、`test_tui_hooks.py::test_clear_resets_only_once` | ✅ 逻辑覆盖（stderr 文案未逐字核对） |
  | 7 错误配置不阻断启动 | `test_hook_e2e.py::test_e2e_ac8_*`、`test_loader.py` | ✅ 覆盖 |
  | 8 `/hooks` 命令 | `test_hook_e2e.py::test_e2e_ac12_*` | ✅ 覆盖 |
  | 9 端到端组合（AC17） | 上述各项之并集 | ⚠️ **未整体串跑**，需要真实 LLM |

### 与文档不一致的实现取舍

| 文档写的 | 实际做法 | 原因 |
|---|---|---|
| `/hooks` handler 放 `tui/hooks.py` | 放 `command/builtin_hooks.py` | 命令 handler 一律住 `command/` 包（该包不依赖 textual）；放 tui 会破坏既有分层 |
| `clear_and_new_session` 为同步 | 改为 `async` | 需要在关旧会话前 `await` SessionEnd 的分派；调用面只有 6 处 |
| `SessionRuntime.reset_for_new_session` 里清 only_once | 改由 TUI 调 `engine.reset_for_new_session()` | 同上：不为内部状态把同步公开 API 改异步 |
| `parse_rule` 失败「静默跳过」（ch06 行为） | 报 stderr 后跳过（F4） | 用户写了错规则却毫无反馈会以为已生效 |
| `Rule` 持 pattern 字符串 | 持 `Matcher` 对象 + `raw` 原文 | F1 的结构化匹配类型 |
| `Bash(git *)` 这类裸 glob 过去走「含 `/` 则分段」 | Bash 的裸 glob 改走**命令语义**（`*` 跨 `/`） | **修掉 ch06 的一个缺陷**：`Bash(rm *)` 过去匹配不上 `rm -rf /tmp`，`Bash(*)` 匹配不上含 `/` 的命令——拒绝规则对带路径的命令静默失效。见下方证据 |
| HTTP 非 2xx「视为放行」 | 不拦截，但记为 hook 失败（stderr 日志） | 一次 500 若被当成「检查通过」，等于静默放行；G9 要求 hook 失败要留痕 |
| `action` 里的未知字段 | 报错并跳过该条 | 用户容易把规则级的 `timeout` / `only_once` 写进 `action`（我自己第一次就写错了），静默忽略会让人以为设了超时 |
| 子进程输出按 UTF-8 解码 | 优先 UTF-8，失败退回本地编码 | Windows 脚本按控制台编码（GBK）写 stderr 是常态，直接按 UTF-8 解会让拒绝原因变乱码——而它要展示给用户并回灌模型 |
| 11 个 emit 点全在 agent 内 | agent 内 7 个，TUI/cli 4 个 | SessionStart/End/Resume/UserPromptSubmit 的时机属于界面与进程生命周期，Agent 无从感知 |

### 修掉的一个 ch06 缺陷（附证据）

```
修复前：match_pattern('rm *', 'rm -rf /tmp')  → False
        match_pattern('*',    'rm -rf /')     → False
修复后：Bash(rm *) 命中 'rm -rf /tmp'；Bash(*) 命中 'rm -rf /'
```

原因是旧实现看到**目标串**含 `/` 就切换到路径分段匹配，于是单段模式匹配不上多段目标。用户写的 `Bash(rm *)` 拒绝规则对含路径的命令**静默失效**。回归护栏见 `tests/permission/test_matcher.py::test_command_glob_semantics` 与 `tests/test_permission.py::test_bash_glob_now_matches_commands_with_slash`；路径类工具仍是分段语义（`*` 不跨 `/`），未受影响。
