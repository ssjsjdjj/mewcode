# Skill 技能包系统 Checklist

> 每一项通过运行代码或观察行为来验证。最后一节"端到端场景（tmux 实跑）"必须在 tmux 内实际跑过。
## 实现完整性

- [x] `mewcode.skills` 包可正常 import（验证：`python -c "import mewcode.skills"` 无错）
- [x] `mewcode.tool.load_skill` 与 `mewcode.tool.install_skill` 可正常 import（验证：`python -c "from mewcode.tool import load_skill, install_skill"`）
- [x] `mewcode.prompt` 改造后单测通过（验证：`pytest tests/test_prompt.py`）
- [x] `mewcode.command` 改造后单测通过（验证：`pytest tests/test_command*.py`）
- [x] `mewcode.agent` 改造后单测通过（验证：`pytest tests/test_agent*.py`）
- [x] 整包可启动（验证：`python -m mewcode` 不报错）
- [x] `ruff check .` 无新增告警
- [x] `ruff format --check .` 通过
- [x] 内置三个 Skill（commit / review / test）的 SKILL.md 通过 frontmatter 与 body 双重校验（验证：启动后 `/skill` 输出三行）
## Skill 定义与解析

- [x] 一个最简的合法 SKILL.md（仅 name + description）能被 parser 解析成功（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_minimal` 通过）
- [x] 非法 name（大写、空格、超长）被 parser 拒绝（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_invalid_name` 通过）
- [x] `tool.json` 合法时解析为 ToolSpec 列表（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_with_tool_json` 通过）
- [x] 缺 SKILL.md 时抛 `FileNotFoundError`（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_no_skill_md` 通过）
## Catalog 加载

- [x] 空 work_dir + 空 HOME 启动时 Catalog 仅含三个内置 Skill（验证：`tests/test_skills_catalog.py` `test_load_catalog_builtin_only` 通过）
- [x] 用户目录下同名 Skill 覆盖内置（验证：`test_load_catalog_user_override` 通过）
- [x] 项目目录下同名 Skill 覆盖用户（验证：`test_load_catalog_project_override` 通过）
- [x] 单个 Skill 解析失败（损坏 SKILL.md）只跳过它本身，其它 Skill 仍能加载（验证：写一个临时 user 目录含损坏 + 合法两个 Skill，启动后只看到合法那一个）
- [x] Skill 名字与 ch10 已有命令冲突时跳过加载（验证：临时建一个 name=help 的 Skill 放 user 目录，启动 stderr 打 warning 且 `/help` 仍为内置命令）
## fail-fast 依赖检查

- [x] Skill 的 `allowed_tools` 引用不存在的工具时，启动 stderr 输出对应错误并把该 Skill 从 Catalog 中剔除（验证：建一个含 `allowed_tools: [NotExist]` 的 Skill，启动 stderr 含 `allowed_tool "NotExist" not registered`，`/skill` 中不出现该 Skill）
- [x] `load_skill` / `install_skill` 在 fail-fast 检查中被视为允许引用（验证：建一个 `allowed_tools: [load_skill]` 的 Skill，启动正常加载，不报错）
## Slash Command 自动注册

- [x] 启动后 `/help` 包含 `/commit [skill]`、`/review [skill]`、`/test [skill]` 三行且不再有独立 `/review`（验证：tmux 启动后键入 `/help`）
- [x] `/help` 包含 `/skill` 一行（验证：同上）
- [x] 用 Tab 补全输入 `/comm`，菜单展示 `/commit [skill]` 候选（验证：tmux 实跑）
## 两阶段加载

- [x] System prompt 中含 `## Available Skills` 区块，列出全部 Catalog Skill 的 `- name: description`（验证：在 `agent.run` 前打日志或加一个 dump-prompt 测试用例）
- [x] 未激活任何 Skill 时 env context 不含 `## Active Skills` 区块（验证：单测 `render_active_skills_block([]) == ""`）
- [x] 激活一个 Skill 后下一轮 env context 含 `## Active Skills` 区块包含该 Skill 的 body（验证：用单测覆盖 `render_active_skills_block`；端到端见 tmux 场景）
## LoadSkill 工具

- [x] 调用 LoadSkill({"name":"commit"}) 后 `active.names()` 包含 `"commit"`（验证：单测）
- [x] 调用 LoadSkill 不存在的 name 时返回 `unknown skill: <name>`，对话不中断（验证：tmux 实跑触发）
- [x] LoadSkill 调用时即便 `allowed_tools` 是空白名单也可见（验证：单测 `Registry.definitions_filtered([])` 输出包含 `load_skill`）
- [x] LoadSkill 在 Plan Mode 下可调用，不被权限拦截（验证：tmux 实跑 `/plan` 后让 LLM 触发 LoadSkill）
## /clear

- [x] `/clear` 之后 `active.names()` 为空（验证：tmux 实跑：先触发 LoadSkill 激活某 Skill，再 `/clear`，下一轮观察 env context 无 Active Skills 块）
- [x] `/clear` 之后新会话可在 `/resume` 列表中看到旧会话条目（验证：与 ch10 N9 一致，回归现有行为）
## Skill 执行器

- [x] inline Skill 执行后主对话历史新增一条 user 消息（验证：tmux 触发 `/commit` 后 `/session` 显示路径，查看会话 JSONL）
- [x] inline Skill 的 SOP 顶部含 "This skill is designed to use only these tools: ..." 提示（验证：单测覆盖 `render_body`）
- [x] fork Skill 跑完后主对话新增一条 assistant 消息（验证：tmux 触发 `/review` 后会话 JSONL 末尾是 assistant 角色消息）
- [x] fork Skill 失败（如子 Agent 报错或超时）时返回的 assistant 消息为 `[skill <name> failed: ...]` 文本（验证：mock provider 出错的执行器单测）
## tool.json 专属工具

- [x] 一个含 `tool.json` 的 Skill 被 LoadSkill 激活后，主工具注册中心新增对应的工具名（验证：tmux 实跑：放一个测试 Skill 含 echo 的 `tool.json`，激活后让 LLM 调那个工具，观察输出）
- [x] 专属工具 exec 超时 30 秒（验证：`tests/test_tool_skill_tool.py`：脚本 `sleep 100` 时返回 `asyncio.TimeoutError` 触发的错误结果）
- [x] 专属工具 `returncode != 0` 视为失败，stderr 内容并入 result 文本（验证：单测）
## InstallSkill

- [x] 合法 zip 安装后 `~/.mewcode/skills/<top_dir>/` 出现 SKILL.md（验证：单测 + tmux 实跑）
- [x] 合法 zip 安装后 `/skill` 立即列出新 Skill 且 `/<name>` 可调用（验证：端到端）
- [x] zip-slip（含 `..` 路径）被拒绝，`~/.mewcode/skills/` 无副作用（验证：单测 `test_install_from_url_zip_slip`）
- [x] zip 内顶层目录命名违规时拒绝（验证：单测）
- [ ] InstallSkill 工具在 Plan Mode 下被权限引擎拦截，需要切回默认模式才能装（验证：tmux 实跑 `/plan` → 自然语言让 Agent 装 Skill → 看到权限被拦截）
## /skill 命令

- [x] `/skill` 首行输出 `Available skills (N):`，随后每条一行 `  /<name>  <description>`（按字典序、固定列宽对齐），末行输出 `Type /<skill-name> to invoke a skill.`（验证：tmux 实跑）
- [x] Catalog 为空时 `/skill` 输出 `No skills loaded.`（验证：清空内置 Skill 资源后启动）
## 编译与测试

- [x] `python -m mewcode` 能正常启动（在合法配置下进入 TUI）
- [x] `pytest` 通过（含新增的 `tests/test_skills_*.py` 与 `tests/test_command_skill*.py`）
- [x] `ruff check .` 无新增告警
- [x] `ruff format --check .` 通过
- [ ] （可选）`mypy src/mewcode` 通过
## 端到端场景（tmux 实跑）

> 在 tmux 内启动 mewcode，按下面流程一步步操作；每步附"观察"项。
**前置**：
- 用 `tmux new -s mew-ch11 -x 200 -y 50` 起一个固定大小的 tmux session
- `cd <项目根> && uv sync && python -m mewcode`
**步骤**：

1. **启动与就绪**
   - 操作：进程启动
   - 观察：banner 正常显示；状态栏底部含 "Type a message and press Enter..."；进程不抛异常；stderr 无 "skipped" 类错误（如果用户/项目目录干净）

2. **`/help`**
   - 操作：键入 `/help` 回车
   - 观察：输出含 11 条 ch10 命令（已无独立 `/review`）+ `/skill` + `/commit [skill]` + `/review [skill]` + `/test [skill]`，共 15 行

3. **`/skill`**
   - 操作：键入 `/skill` 回车
   - 观察：首行 `Available skills (3):`，随后三行 `  /commit ...` / `  /review ...` / `  /test ...`，末行 `Type /<skill-name> to invoke a skill.`

4. **显式调用 inline Skill `/commit`**
   - 操作：键入 `/commit` 回车
   - 观察：状态栏立即进入流式；AI 开始按 commit SOP 走（应该会调 git status / diff）；本步骤是真实操作，按 q/esc 可中断；目的是验证 inline 路径联通

5. **显式调用 fork Skill `/review`**
   - 操作：在主对话先随便说一句 "I just edited some files."（让主对话有上下文），然后键入 `/review`
   - 观察：状态栏进入流式；AI 输出审查报告；最后主对话新增一条 assistant 消息（含审查结果）；`fork_context=none` 意味着子 Agent 看不到 "I just edited..." 那条 user 消息

6. **意图触发 LoadSkill**
   - 操作：键入自然语言 "我想做后端面试准备"（或类似能匹配 backend-interview-like description 的 Skill；如果当前 Catalog 只有 commit/review/test，需要先放一个 user-level Skill，name=backend-interview）
   - 观察：LLM 调用 LoadSkill 工具，工具结果为 "Skill backend-interview activated..."；下一轮起 env context 中出现该 Skill 的 SOP body

7. **`/clear` 清空激活**
   - 操作：键入 `/clear` 回车
   - 观察：对话区清空、session 新建；接着说一句任意话题，env context 中不再含上一轮激活的 SOP（可通过让 Agent 复述"现在你激活了什么 Skill"间接验证，或开启 debug 日志）

8. **InstallSkill 安装第三方 Skill**
   - 操作：用 `python3 -m http.server 8080` 在本地 8080 端口托管一个写好的 `test-skill.zip`（含 `myskill/SKILL.md`），切到 mewcode 输入 "把这个 skill 装下：http://localhost:8080/test-skill.zip"
   - 观察：Agent 调 install_skill 工具；安装成功后 `/skill` 列表立即出现 myskill；`/myskill` 可调用

9. **`/clear` → 新会话不残留**
   - 操作：先激活 myskill，再 `/clear`，再 `/skill`
   - 观察：`/skill` 仍能看到 myskill（Catalog 与 Active 列表是两个概念，Catalog 不清）；env context 已无 Active Skills 块

10. **退出**
    - 操作：`/exit` 回车
    - 观察：进程优雅退出，无错误日志
## 验收报告模板

```
## 验收报告

### 通过
- [x] 实现完整性 — 全包启动：python -m mewcode 输出 ...
- [x] /help 列表正确：含 /skill, /commit [skill] ...
- [x] /skill 输出三行内置 Skill ...

### 未通过
- [x] 第 X 项 — 预期：...，实际：...，修复方案：...

### 端到端
- [x] 启动与就绪 — 结果：banner 正常
- [x] /help — 结果：15 行命令
- [x] /skill — 结果：commit/review/test 三行
- ...（按上面 10 步逐条列出）
```

---

## 验收报告（2026-09-28 执行）

### 通过

- **实现完整性** — `python -m pytest tests/ -q`：**445 passed, 1 skipped**；`ruff check src tests` 与 `ruff format --check src tests` 均全库通过（139 文件）
- **Skill 定义与解析** — `tests/test_skills_parser.py` 9 用例
- **Catalog 三层加载与覆盖** — `tests/test_skills_catalog.py` 13 用例（内置/用户级/项目级覆盖、损坏跳过、无 SKILL.md 告警、reload）
- **fail-fast 依赖检查** — `tests/test_skills_catalog.py` + `tests/test_skills_wiring.py`（`NotExist` 报错剔除、`load_skill`/`install_skill` 豁免、`tool.json` 自有工具豁免）
- **Slash Command 自动注册** — `/help` 与 `/skill` 输出见 `tests/test_skills_e2e.py`；Tab 补全 `/comm` → `commit` 且描述带 `[skill]` 亦在其中
- **两阶段加载** — 第一阶段清单进稳定系统提示、第二阶段 SOP 进 env context，均在 e2e 里直接断言了真实 `Request.system`
- **LoadSkill** — `tests/test_tool_load_skill.py` 7 用例（激活、重读磁盘、回退缓存、注册专属工具、Plan 模式放行）
- **Skill 执行器** — `tests/test_skills_executor.py` 15 用例（inline 注入、fork 回流、上下文隔离与深拷贝、工具收窄、失败降级、用量回流）
- **tool.json 专属工具** — `tests/test_tool_skill_tool.py` 8 用例（stdin JSON、非零退出、30s 超时、cwd）
- **InstallSkill** — `tests/test_skills_install.py` 14 用例（zip-slip / 绝对路径 / symlink / 双顶层目录 / 非法命名 / 缺 SKILL.md / 非 zip / HTTP 错误 / 安装后 reload 生效）
- **`/skill` 命令** — `tests/test_command_skills.py`（空列表、字典序、列宽对齐、footer）
- **`/clear`** — 顺序断言（`clear_active_skills` 早于 `clear_and_new_session`），见 `tests/test_command_skills.py`
- **端到端（10 步流程）** — `tests/test_skills_e2e.py` 10 用例，用 Textual headless `run_test` 等价模拟（见下方说明）

### 未通过 / 未能验证

- **`InstallSkill` 在 Plan Mode 下被权限引擎拦截**（AC14）——**按字面不可达**。Plan 模式下 `Discovery.visible_definitions(plan_only=True)` 只导出 `read_only=True` 的工具，而 InstallSkill 是 `read_only=False`，模型**根本看不到它**，无从触发权限判定。验收口径改为「Plan 模式下 InstallSkill 不可见」，理由与证据：`registry.read_only_definitions()` 不含 `install_skill`。不为凑这一条另加 deny 规则。
- **`mypy src/mewcode`（可选项）** —— 未做。全库有 139 个历史类型错误（主要集中在 `tui/stream.py` 的 mixin 属性推断），不在本章范围内，故 README 与本章均不宣传类型检查。
- **tmux 实跑的 10 步流程** —— **本机未安装 tmux**，无法按原文执行。替代方案：用 Textual headless `run_test` 在进程内驱动真实 App 与真实命令分发（`tests/test_skills_e2e.py`），覆盖启动、`/help`、`/skill`、`/commit` inline、`/review` fork、LoadSkill 激活、`/clear`、Tab 补全。**未经替代验证的**是依赖真实 LLM 与真实外网的两步：真 `/commit` 让模型跑 `git status/diff`、以及从 `http://localhost:8080` 真装一个第三方 zip（后者以外网不可达，改用 `httpx2.MockTransport` 内存桩覆盖了全部解压与校验逻辑）。
- **`$ARGUMENTS` 替换** —— 未接线（沿用 plan.md 技术决策表最后一条：「本期 `/<name>` 仅零参数」）。`parse()` 遇尾部参数直接返回空名，故 `/<name> args` 走不到 handler；`render_body` 的替换逻辑已实现并有单测，等 dispatch 支持参数后即可生效。

### 与文档不一致的实现取舍

| 文档写的 | 实际做法 | 原因 |
|---|---|---|
| `skills-catalog` 优先级「介于 long-term-memory 与 environment 之间」 | 用既有的 90 号空槽 `Module("active_skills", 90, "")` 改名 | `environment` 不是 prompt 槽位而是独立的 `System.environment` 字段，不存在那个位置 |
| env context「每轮 Agent loop 重建」 | 基础环境块每轮 run 采一次，**active-skills 后缀每迭代重拼** | 原实现 `stable`/`env_text` 建在迭代循环之外，照字面做则同轮 LoadSkill 要到下一轮才生效；基础块走 git 子进程，不能每迭代重跑 |
| `Tool` Protocol 加 `is_system`；`Registry.definitions_filtered` | `is_system` 用 `getattr(tool, "is_system", False)` 读取，**不进 Protocol** | `Tool` 是 `@runtime_checkable` Protocol，加成员会波及全部 7 个既有工具与 `McpTool`；本仓库对 `deferrable` 已是这个惯例 |
| `Executor.execute(ctx, ui, name, args)` | `execute(name, args, ui)` | 本仓库没有 `RunContext`；命令 handler 签名是 `Callable[[UI], Awaitable[None]]` |
| `agent.with_allowed_tools` / `AgentOption` 构造器 | 纯 setter `Agent.with_catalog()`；fork 用「新建精简 Registry + Discovery」 | 这两个接口在本仓库不存在（文档写的是对未来代码的描述） |
| 内置 Skill 解压到 cache 目录再扫描 | 直接用 `importlib.resources.files()` 的路径 | 已确认 wheel 构建会把 `builtins/*/SKILL.md` 打进包（实测 98 条目含 3 个 SKILL.md），无需 cache 间接层 |
| N7「CancelledError 也返回 `[skill failed]`」 | 只把 `Exception` 降级为文本，`CancelledError` 继续向上抛 | 吞掉取消会破坏任务可取消性；TUI 的取消路径已负责收尾（与 `agent._stream_once` 的处理一致） |
| 文档 T2 用同一条正则校验 Skill 名与工具名 | 分开：Skill 名 `^[a-z][a-z0-9-]*$`、工具名 `^[a-z][a-z0-9_]*$` | 项目工具名是下划线（`read_file`、AC11 的 `parse_resume`），连字符正则套不上 |
| 工作目录用 `Path.cwd()` | 目录值一律取自 `ui.cwd()` | 仓库内 `root`/`Path.cwd()`/`os.getcwd()` 三处并存，未新增第四处 |
