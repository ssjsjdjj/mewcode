# 🐱 MewCode 开发全记录 — 从小白到入门

> 本文档记录了 MewCode 这个项目的完整开发过程，面向零基础读者。
> 每一步都会解释「这是什么」「为什么要这样做」「背后的概念是什么」。

---

## 目录

1. [项目概览：我们要做什么？](#1-项目概览我们要做什么)
2. [什么是 mew-spec 开发流程？](#2-什么是-mew-spec-开发流程)
3. [阶段一：需求分析（Spec）](#3-阶段一需求分析spec)
4. [阶段二：技术设计（Plan）](#4-阶段二技术设计plan)
5. [阶段三：任务拆解（Task）](#5-阶段三任务拆解task)
6. [阶段四：验收清单（Checklist）](#6-阶段四验收清单checklist)
7. [阶段五：开发实现](#7-阶段五开发实现)
8. [阶段六：验收测试](#8-阶段六验收测试)
9. [项目结构与文件说明](#9-项目结构与文件说明)
10. [配置与使用方法](#10-配置与使用方法)
11. [常见概念解释](#11-常见概念解释)
12. [后续可以做什么](#12-后续可以做什么)

---

## 1. 项目概览：我们要做什么？

### 1.1 项目目标

我们要做一个叫 **MewCode** 的程序。它运行在**终端/命令行**里（就是那个黑乎乎的窗口），
让你可以直接在里面和 AI 聊天，就像用 ChatGPT 网页版一样，但不用打开浏览器。

### 1.2 为什么要做这个？

- **Claude Code** 是一个很流行的 AI 编程助手，在终端里运行。我们想做一个类似的东西，但更轻量、更灵活。
- 很多 AI 工具只支持一家厂商（比如只能用 OpenAI 或只能用 Anthropic），
  我们想做一个**可以自由切换后端**的工具。
- 这个版本（v0.1.0）只做**纯聊天**，先打通最基础的通话功能。
  以后可以慢慢加上代码编辑、文件操作等高级功能。

### 1.3 目标用户

- 开发者，习惯在终端里工作
- 想用一个工具切换多家 AI 模型的人
- 对 AI 编程助手感兴趣的人

### 1.4 开发环境

| 项目 | 内容 |
|------|------|
| 开发语言 | Python 3.9+ |
| 操作系统 | Windows（理论上跨平台） |
| 项目位置 | `C:\Users\Zhouyuhang\Desktop\mewcode\` |

---

## 2. 什么是 mew-spec 开发流程？

### 2.1 背景

写代码最容易犯的错误是什么？**想清楚了再动手**其实是反人性的——人天性喜欢直接动手。
结果常常是：写了一半发现需求没搞明白，推倒重来。

**mew-spec** 是一个开发流程，强制你在写代码之前先想清楚四个问题：

```
第1步：spec.md    → 想清楚「要做什么」
第2步：plan.md    → 想清楚「怎么做」
第3步：task.md    → 想清楚「先做什么后做什么」
第4步：checklist.md → 想清楚「怎么才算做完了」
```

**只有四份文档都获得你批准之后，才能开始写代码。**

### 2.2 每一份文档的职责

可以用盖房子来类比：

| 文档 | 类比 | 回答的问题 |
|------|------|-----------|
| spec.md | 设计图纸需求书 | 房子盖多大？几个房间？要不要阳台？ |
| plan.md | 施工方案 | 地基怎么打？墙用什么材料？水电怎么走？ |
| task.md | 施工进度表 | 先挖地基还是先买材料？每一步做完怎么检查？ |
| checklist.md | 验收清单 | 门能打开吗？灯亮吗？下水道堵不堵？ |

### 2.3 为什么这么麻烦？

直接写代码不是更快吗？

- **「这个太简单了，不需要写 spec」** → 越简单的东西，没说出来假设越多。
  比如你说「做一个聊天机器人」，你的假设可能是用 OpenAI，
  但我可能以为用 Anthropic，两个人想的根本不是同一个东西。
- **写文档就是在和未来的自己沟通。** 过两周你再回来看这个项目，
  有文档就能秒懂当初为什么这么设计。
- **先想清楚再做，返工率低。** 在文档里改一个设计只需要 5 分钟，
  在代码里改则可能花 2 小时。

### 2.4 流程总图

```
你的一个想法
     │
     ▼
阶段一：需求澄清 → 写出 spec.md → 给你看 → 你同意了？
     │                                              │ 不通过：修改
     │                                              ▼ 通过
阶段二：技术设计 → 写出 plan.md → 给你看 → 你同意了？
     │                                              │ 不通过：修改
     │                                              ▼ 通过
阶段三：任务拆解 → 写出 task.md → 给你看 → 你同意了？
     │                                              │ 不通过：修改
     │                                              ▼ 通过
阶段四：验收设计 → 写出 checklist.md → 给你看 → 你同意了？
     │                                              │ 不通过：修改
     │                                              ▼ 通过
阶段五：开始写代码（按 task.md 一步步来）
     │
     ▼
阶段六：按 checklist.md 逐项验收
```

### 2.5 几个原则

- **一次只问一个问题** —— 不会一下子问你十个问题把你搞晕
- **能用选择题就不用开放题** —— 「用 Python 还是 Go？」比「你想用什么语言？」好回答
- **每份文档批准后才能进入下一阶段** —— 避免前面没想清楚就往下走
- **先有证据再下结论** —— 「跑一下看看」比「应该没问题」可靠

---

## 3. 阶段一：需求分析（Spec）

### 3.1 什么是 Spec？

Spec = Specification（规格说明书）。

它是一个项目开始前必须写的文档，回答一个核心问题：**我们要做什么？**

不要写具体怎么做（那是 plan 的事），只写**用户能感受到的功能**。

### 3.2 需求澄清过程

一开始我只知道一个大概的方向：「做一个终端 AI 助手」。

然后我们通过一问一答的方式，**一次只问一个问题**来澄清细节。

**第一个问题：用什么语言开发？**

为什么要问这个？因为不同的语言适合不同的场景：

| 语言 | 优点 | 缺点 |
|------|------|------|
| **Python**（我们选的） | 开发快、生态好、Textual 这个 TUI 库很成熟 | 性能一般、打包略麻烦 |
| Go | 单二进制文件、性能好、并发强 | TUI 库没那么丰富 |
| Rust | 性能最强 | 学习曲线陡、开发慢 |
| TypeScript/Node.js | 前端开发者友好、npm 生态 | 终端体验不如 Python 的 Textual |

我们选了 **Python**，因为开发速度最快，适合快速验证想法。

### 3.3 Spec 的核心内容（逐段呈现在你面前）

写 spec 时不是一口气全丢给你，而是**分成 5 段，每段你确认了再写下一段**：

#### 第1段：背景与目标

**背景：** 目前终端中与 AI 交互主要有两种方式：
1. 打开 Web 界面（如 ChatGPT 网页）—— 需要来回切换窗口，很烦
2. 用官方的 CLI 工具（如 Claude Code）—— 但通常绑定一家厂商

**目标：** 做一个叫 MewCode 的终端 AI 助手，可以自由切换后端（Anthropic 或 OpenAI），
第一期只做纯对话。

你确认了：「符合」。

#### 第2段：功能需求

我们定义了 7 条功能需求（后来你改成了更详细的 12 条）:

**F1 - 配置加载：** 程序启动时读取一个 YAML 文件，里面写了 AI 厂商的配置信息
（如 API 地址、密钥、模型名等）。如果配置有问题（比如少了密钥），
启动时就报错退出，而不是运行到一半才崩溃。

**F2 - Provider 选择：** 如果配置文件里只有一个 AI 厂商，直接用它；
如果有多个，启动时显示一个列表让你选。

**F3 - 多协议适配：** 支持 Anthropic 和 OpenAI 两种 API 格式。
它们的请求格式、返回格式都不一样，我们要在背后做转换，
让上面的界面代码不用关心底下是哪个厂商。

**F4 - 发起对话：** 把系统提示词 + 历史聊天记录打包，发给 AI。

**F5 - 流式接收：** AI 回复不是一下子全部返回的，而是一段一段（像打字一样）回来的。
我们要边收边显示，而不是等全部收完再一次性展示。

**F6 - 多轮上下文：** AI 要能记住之前说过的话。你问「我的名字是什么」，
如果之前说过「我叫小明」，它应该能回答「你的名字是小明」。

**F7 - TUI 界面布局：** 启动后显示一个漂亮的终端界面，包含：
- 顶部：一只猫咪 ASCII 画 + "MewCode v0.1.0" + 当前目录
- 对话区：显示你和 AI 的对话记录
- 底部输入框：你打字的地方，有 ❯ 提示符
- 状态栏：显示当前用的 AI 厂商和模型名

**F8 - 流式呈现与渲染：** 回复时逐字显示（像打字效果），
结束后自动美化排版（代码块、列表、加粗等 Markdown 效果）。

**F9 - 输入与提交：** 按 Enter 发送，按 Alt+Enter 换行（写多行内容）。
发送后输入框自动清空。

**F10 - 退出：** 输入 /exit 或按 Ctrl+C 都可以安全退出。

**F11 - 错误反馈：** 如果 API 密钥不对、网络断了、模型不存在等，
在对话区显示错误信息，但程序不退出，你可以继续问。

**F12 - 响应计时：** 从发出请求开始计时，显示 "Imagining… (3s)"，
秒数实时递增。结束后显示总耗时。

#### 第4段：不做的事（非常重要！）

这一阶段**明确排除**了以下功能（不是以后不做，而是这期不做）：

- ❌ 工具调用 / function calling —— 不让 AI 去执行代码或操作文件
- ❌ MCP 集成 —— 不连接外部服务
- ❌ 权限系统 —— 不需要授权确认
- ❌ 上下文压缩 —— 聊天记录太长也不做截断（留给以后）
- ❌ 会话持久化 —— 退出后聊天记录不保存
- ❌ slash 命令体系 —— 除了 /exit，不做 /help、/clear 等命令
- ❌ thinking 内容展示 —— Claude 的思考过程不显示
- ❌ 流式中断 —— 不能取消正在生成的回复
- ❌ 自动重试 —— 出错就提示，不自动重试
- ❌ 用量统计 —— 不显示 token 数和费用
- ❌ 多模态 —— 不支持图片输入

**为什么要明确写「不做的事」？** 因为不说清楚，开发者和用户都会有各种预期。
把这些边界划清楚，大家就知道这期做到什么程度为止。

#### 第5段：验收标准

每条功能需求都绑定了至少一条验收标准：
- "给一个错误的 API key → 看到错误提示 → 程序没崩溃 → 可以继续问"
- "连着问 3 轮 → AI 能引用前文"
- "按 /exit → 安全退出 → 终端没乱"

### 3.4 什么是 YAML？

YAML（读作"雅猫"）是一种配置文件格式，比 JSON 更容易阅读。

对比一下：

**JSON 格式：**
```json
{
  "providers": [
    {
      "name": "my-claude",
      "protocol": "anthropic",
      "model": "claude-sonnet-5-20251001"
    }
  ]
}
```

**YAML 格式（我们用的）：**
```yaml
providers:
  - name: my-claude
    protocol: anthropic
    model: claude-sonnet-5-20251001
```

YAML 用缩进表示层级关系（像 Python 一样），没有大括号和逗号，更清爽。

### 3.5 配置的 6 个字段

| 字段 | 中文 | 必填 | 说明 |
|------|------|------|------|
| `name` | 名字 | ✅ | 给这个配置取个名字，方便区分 |
| `protocol` | 协议 | ✅ | 用哪家的 API：`anthropic` 或 `openai` |
| `model` | 模型 | ✅ | 模型名，如 `gpt-4o`、`claude-sonnet-5-20251001` |
| `base_url` | 地址 | ✅ | API 的请求地址 |
| `api_key` | 密钥 | ✅ | 你的 API 密钥（保密！） |
| `thinking` | 思考 | ❌ | 是否开启 Claude 的深度思考模式，默认关闭 |

---

## 4. 阶段二：技术设计（Plan）

### 4.1 什么是 Plan？

Plan 回答的问题是：**我们怎么做？**

spec 说"我们要一个能聊天的终端程序"，
plan 说"那我们把它分成 4 层，每一层负责什么，每一层用什么技术"。

### 4.2 四层架构

```
┌──────────────────────────────────────────────┐
│               TUI 层（界面）                   │
│   负责：显示界面、接收输入、展示回复           │
│   技术：Textual（Python 的 TUI 框架）         │
├──────────────────────────────────────────────┤
│              Session 层（协调）               │
│   负责：管理聊天历史、协调请求流程            │
├──────────────────────────────────────────────┤
│             Provider 层（AI 适配）            │
│   负责：封装不同 AI 厂商的 API 差异           │
│   ┌──────────────┐  ┌──────────────┐        │
│   │ Anthropic    │  │ OpenAI       │        │
│   │ Provider     │  │ Provider     │        │
│   └──────────────┘  └──────────────┘        │
├──────────────────────────────────────────────┤
│             Config 层（配置）                 │
│   负责：读取 YAML 文件，解析配置              │
└──────────────────────────────────────────────┘
```

**为什么分成 4 层？**

- **职责分离**：每一层只管自己的事，不混在一起
- **可替换性**：想加一个新的 AI 厂商，只需要在 Provider 层加一个新文件
- **便于测试**：每一层可以单独测试

### 4.3 核心数据（代码里的"数据类"）

数据类（`@dataclass`）是 Python 的一种轻量级类，主要用来存数据：

```python
@dataclass
class ProviderConfig:
    name: str        # 供应商标识名
    protocol: str    # "anthropic" | "openai"
    model: str       # 模型名
    base_url: str    # API 地址
    api_key: str     # 密钥
    thinking: bool   # 是否开启深度思考
```

这就像一个**表格的列定义**——规定了每个供应商配置应该有哪些信息。

### 4.4 什么是 stream（流式）？

传统的 API 调用是这样的：

```
你 → 发请求 → 等 5 秒 → 收到完整回复
```

流式是这样的：

```
你 → 发请求 → 收到"你" → 收到"好" → 收到"吗" → 收到""（结束）
```

就像刷抖音——视频是一帧一帧来的，不是等整部电影下载完才播放。

**SSE**（Server-Sent Events，服务器推送事件）是实现流式的一种标准技术。
AI 厂商的 API 基本都用它。

### 4.5 什么是 Provider 工厂模式？

工厂模式是一种设计模式，意思是：

> 你不直接说「我要创建一个 Anthropic 的 Provider」，
> 你告诉工厂「我要一个 协议类型为 anthropic 的 Provider」，
> 工厂帮你创建好。

好处：如果你想换厂商，只需要改配置文件里的 `protocol` 字段，
不用改代码。

### 4.6 技术选型决策

**为什么用 Textual 而不是其他 TUI 框架？**

| 框架 | 特点 |
|------|------|
| **Textual**（我们选的） | 纯 Python、CSS 样式、异步优先、组件丰富 |
| Rich | 只能输出富文本，不能做交互式界面 |
| prompt_toolkit | 功能强但手动组合组件太麻烦 |
| curses | 太底层，相当于用砖头砌房子 |

**为什么用 httpx 而不是官方 SDK？**

| 方案 | 优点 | 缺点 |
|------|------|------|
| 官方 SDK（anthropic + openai） | 开箱即用 | 两个 SDK 接口不同，难统一 |
| **httpx**（我们选的） | 统一底层传输 | 要自己解析 SSE |

我们选了 httpx，因为：
1. 两个 SDK 的流式接口差异很大，分开适配反而更麻烦
2. 直接在 HTTP 层面统一，更干净可控
3. 减少两个大依赖包

---

## 5. 阶段三：任务拆解（Task）

### 5.1 什么是 Task？

Task 把 plan 里的每个模块**拆成 2-5 分钟的小任务**，
按依赖关系排好顺序。

就像搬家：
- 把「搬家」拆成：打包 → 叫车 → 装车 → 到新家 → 卸车 → 拆包
- 每个步骤都有明确的完成标准

### 5.2 完整的文件清单

我们一共创建了 **28 个文件**。

**每个文件夹的职责：**

| 目录 | 用途 |
|------|------|
| `config/` | 配置相关（加载配置文件、定义数据格式） |
| `providers/` | 和 AI 厂商通信（抽象基类 + Anthropic + OpenAI + 工厂） |
| `session/` | 管理对话（记住聊天历史、编排请求过程） |
| `tui/widgets/` | 界面组件（横幅、输入框、消息气泡、状态栏、计时器） |
| `tui/screens/` | 界面页面（主对话页、Provider 选择页） |
| `tui/css/` | 界面样式（颜色、间距、布局） |

### 5.3 12 个任务的执行顺序

```
T1（项目骨架） → T2（抽象基类）
                    ↓
               ┌────┴────┐
               T3        T4
           (Anthropic)  (OpenAI)   ← T3和T4互不依赖，可以同时做
               └────┬────┘
                    ↓
               T5（工厂 + 会话管理）
                    ↓
          T6（TUI 基础框架）
                    ↓
          T7（输入框）
                    ↓
          T8（消息列表 + 计时器）
                    ↓
          T9（主对话界面，把前面所有组件拼起来）
                    ↓
          T10（Provider 选择 + 启动串联）
                    ↓
          T11（退出 + 错误处理完善）
                    ↓
          T12（示例配置 + 说明文档 + 最终验收）
```

**为什么按这个顺序？**
- 下层的先做（config → providers → session → tui）
- 没有依赖的先做（T3 和 T4 互不依赖，可以并行）
- 最后一口气组装（T9 把所有组件拼起来）

### 5.4 每个任务的设计思路

**T1 — 项目骨架：**
就像盖房子先搭脚手架。创建最基本的文件结构、
装好 Python 依赖包、写好配置文件加载和检查逻辑。

**T2 — Provider 抽象基类：**
先定义好一系列规定（就像先定好充电接口的规格），
后续具体厂商只需要按这个规格实现。

**T3/T4 — 两个厂商实现：**
就像做两个充电头（Type-C 和 Lightning 各一个），
虽然里面的电路不同，但对外接口是一样的。

**T5 — 工厂 + 会话管理：**
工厂是"你要什么充电头，我给你拿"；
会话管理是"记得之前聊了什么"。

**T6-T9 — TUI 界面：**
一层层搭界面，从底向上：
- 先做单个组件（横幅、输入框、消息气泡）
- 再用组件拼成完整的聊天界面
- 最后把所有逻辑连通

---

## 6. 阶段四：验收清单（Checklist）

### 6.1 什么是 Checklist？

Checklist 回答的问题是：**怎么才算做完了？**

在开始写代码之前，就要想好怎么验收。
就像做菜之前先想好「这道菜要咸还是辣？多熟才算好？」。

### 6.2 核心验收项目

**配置相关：**
- ✅ 只有一个 provider 时直接进入对话（不显示选择列表）
- ✅ 配置缺少 api_key 时显示清晰错误，不崩溃
- ✅ YAML 格式错误时同样友好提示

**聊天功能：**
- ✅ Anthropic 和 OpenAI 都能正常对话
- ✅ 回复逐字流式出现（不是一下全部出现）
- ✅ 开启 thinking 时界面不显示思考内容
- ✅ 连问 3 轮能引用前文信息
- ✅ 退出重启后历史清空

**界面交互：**
- ✅ 启动后看到猫咪 banner + 版本号 + 工作目录
- ✅ 输入框有 ❯ 提示符和占位文字
- ✅ Alt+Enter 换行 / Enter 提交
- ✅ /exit 和 Ctrl+C 都能安全退出
- ✅ 退出后终端不残留乱码

**错误处理：**
- ✅ 错误 key → 对话区显示错误 → 程序不退出
- ✅ 不存在的模型 → 同上
- ✅ 网络断开 → 显示连接错误

**计时功能：**
- ✅ 发出请求就显示 "Imagining… (0s)"，秒数递增
- ✅ 结束后显示总耗时

### 6.3 端到端场景

我们还设计了几个完整场景来测试：

1. **正常对话**：启动 → 问好 → 看到流式回复 → 追问上一个问题 → AI 记得
2. **多 provider 选择**：配两个厂商 → 启动 → 选择列表 → 选一个 → 对话
3. **错误恢复**：配错误 key → 启动 → 发送 → 看到错误 → 改对 → 重启 → 正常工作
4. **思考模式**：配 thinking: true → 复杂问题 → 只看到正文

---

## 7. 阶段五：开发实现

### 7.1 开发的核心原则

- **按 task.md 的顺序执行**，不跳步
- **每个任务完成后必须验证**，「应该没问题」不算数
- **先有证据再下结论**——先运行命令看结果，再报告状态
- **被阻塞了不猜，停下来问**

### 7.2 关键代码片段解释

#### 🎯 Provider 抽象基类（providers/base.py）

```python
class LLMProvider(ABC):
    """抽象基类。ABC = Abstract Base Class（抽象基类）。
    它定义了一个"接口规范"：所有 AI 厂商必须实现 chat_stream 这个方法。"""

    @abstractmethod
    async def chat_stream(self, system, messages):
        """发起流式对话。
        - system: 系统提示词（告诉 AI 它是谁）
        - messages: 聊天历史
        - 返回值: 一个"异步生成器"，不断产出事件（文字增量/思考增量/结束/错误）
        """
        ...
```

**为什么需要这个？** 如果不定义规范，A 厂商返回的格式是一种，
B 厂商返回的是另一种，上层的聊天界面就得分别处理，代码会变得非常混乱。

#### 🎯 Anthropic 实现的关键部分（providers/anthropic.py）

```python
# 这是发送给 Anthropic API 的请求体
body = {
    "model": self.config.model,          # 模型名
    "system": system,                     # 系统提示词
    "messages": [                         # 聊天历史
        {"role": m.role, "content": m.content}
        for m in messages
    ],
    "stream": True,                       # 开启流式
    "max_tokens": 8192,                   # 最大回复长度
}

# 如果开启了深度思考
if self.config.thinking:
    body["thinking"] = {"type": "enabled", "budget_tokens": 16000}

# 通过 httpx 发送请求，并一行一行读取返回结果
async with self._client.stream("POST", "/v1/messages", json=body) as response:
    async for line in response.aiter_lines():
        # 分析每一行数据，判断是正文增量、思考增量还是结束信号
        if event_type == "content_block_delta":
            if delta_type == "text_delta":
                yield TextDelta(text=内容)     # 产出正文
            elif delta_type == "thinking_delta":
                yield ThinkingDelta(text=思考内容)  # 产出思考内容
```

#### 🎯 流式事件类型（providers/base.py）

```python
@dataclass
class TextDelta:
    """回复文本增量——最终的显示内容。"""
    text: str

@dataclass
class ThinkingDelta:
    """思考过程增量——收到后丢弃，不显示。"""
    text: str

@dataclass
class Done:
    """流结束标志。"""
    pass

@dataclass
class Error:
    """错误事件。"""
    message: str
    recoverable: bool = True  # 是否可恢复（True = 程序不退出）
```

这四种事件类型组成了 Provider 层的**输出语言**。
不管底层是哪个厂商，产出的都是这四种事件。

#### 🎯 会话管理（session/chat.py）

```python
class ChatSession:
    def __init__(self, provider, system_prompt):
        self.provider = provider      # 当前用的 AI 厂商
        self.system_prompt = system_prompt  # 系统提示词
        self.history = []             # 聊天历史（内存中）

    def add_message(self, msg):
        """向历史追加一条消息。"""
        self.history.append(msg)

    async def request(self):
        """发起一次请求。
        1. 把系统提示词 + 历史传给 provider
        2. 逐个产出事件（文字、思考、错误、结束）
        3. 流结束后把 AI 的完整回复存入历史
        """
        full_text = []
        async for event in self.provider.chat_stream(system, self.history):
            if isinstance(event, TextDelta):
                full_text.append(event.text)  # 收集文字
            yield event  # 透传给上层界面

        # 把完整回复追加到历史
        self.add_message(ChatMessage("assistant", "".join(full_text)))
```

**为什么要把完整回复存到历史？** 
因为下一轮对话时，需要把之前的完整对话都发给 AI，
它才知道前文说了什么。

#### 🎯 TUI 界面（Textual 框架）

Textual 是一个 Python 的 TUI（终端用户界面）框架。

**它的核心概念：**

| 概念 | 说明 | 类比 |
|------|------|------|
| App | 整个应用 | 房子的框架 |
| Screen | 一个页面 | 客厅、卧室 |
| Widget | 界面组件 | 沙发、桌子、灯 |
| CSS | 样式 | 墙的颜色、家具的材质 |
| Message | 事件信号 | 按了开关 → 灯亮 |

**我们的界面组件树：**

```
App（MewCodeApp）
  └── ChatScreen（主聊天界面）
        ├── Banner（猫咪横幅）
        ├── ReadyHint（就绪提示）
        ├── MessageList（对话列表）
        │     ├── MessageBubble（用户消息）
        │     ├── MessageBubble（AI 回复）
        │     └── MessageBubble（错误消息）
        ├── TimerIndicator（计时器）
        ├── InputBox（输入框）
        └── StatusBar（状态栏）
```

**为什么不直接用 print/input 来做交互界面？**

因为 print/input 只能做最简单的问答：
```
你：你好
AI：你好呀
你：_
```

而用 Textual 可以实现：
```
┌─────────────────────────────────────────┐
│     /\_/\                               │
│    ( o.o )  MewCode v0.1.0             │
│     >^·^<                               │
│  C:\Users\...                            │
│                                         │
│  Ready — send a message to start.        │
│  ┌─────────────────────────────────────┐ │
│  │ ❯ 你好                              │ │
│  │ 你好！有什么我可以帮你的？          │ │
│  │ *Imagining… (0s)*                   │ │
│  └─────────────────────────────────────┘ │
│  my-claude        claude-sonnet-5        │
└─────────────────────────────────────────┘
```

#### 🎯 流式显示的核心逻辑（chat_screen.py）

```python
# 当用户在输入框按 Enter 时：
def on_input_box_submitted(self, event):
    text = event.text  # 获取输入内容
    
    # 1. 处理 /exit 命令
    if text == "/exit":
        self.app.exit()
        return
        
    # 2. 显示用户消息
    message_list.add_user_message(text)
    
    # 3. 存入会话历史
    self._session.add_message(ChatMessage("user", text))
    
    # 4. 禁用输入框（不能一边生成一边输入）
    input_box.set_enabled(False)
    
    # 5. 开始计时
    timer.start()
    
    # 6. 创建 AI 回复的气泡
    bubble = message_list.start_assistant_message()
    
    # 7. 启动异步任务处理流式接收
    self._stream_task = asyncio.create_task(
        self._handle_stream(bubble)
    )

# 流式接收处理
async def _handle_stream(self, bubble):
    full_text = []
    async for event in self._session.request():
        if isinstance(event, TextDelta):
            full_text.append(event.text)
            bubble.update_content("".join(full_text))  # 实时更新显示
        elif isinstance(event, ThinkingDelta):
            pass  # 思考内容，丢弃
        elif isinstance(event, Error):
            self._show_error(event.message)  # 显示错误
        elif isinstance(event, Done):
            break  # 结束
    
    # 流结束后
    timer.stop()
    bubble.finalize()        # 重新用 Markdown 美化
    input_box.set_enabled(True)  # 恢复输入
```

---

## 8. 阶段六：验收测试

### 8.1 自动化测试

开发过程中，每个任务完成后我们都会运行验证。

举个实际的测试例子：

```python
# 1. 创建模拟 Provider（不真的连 AI）
class MockProvider:
    async def chat_stream(self, system, messages):
        yield TextDelta(text='Hello! ')
        yield TextDelta(text='MewCode.')
        yield Done()

# 2. 创建会话
session = ChatSession(MockProvider())
session.add_message(ChatMessage('user', 'Hi!'))

# 3. 接收回复
texts = []
async for event in session.request():
    if isinstance(event, TextDelta):
        texts.append(event.text)

# 4. 验证
assert ''.join(texts) == 'Hello! MewCode.'
assert len(session.get_history()) == 2  # user + assistant
```

**测试结果：全部通过 ✅**

- ✅ 正常对话：回复拼接正确
- ✅ 多轮对话：历史记录完整
- ✅ 清空历史：正确归零
- ✅ 错误处理：错误事件正确捕获
- ✅ 未知协议：工厂正确拒绝
- ✅ 配置加载：正确解析 YAML
- ✅ 配置校验：缺字段报错、格式错误报错

### 8.2 为什么要用模拟测试而不是真实 API？

1. **速度**：模拟测试毫秒级完成，真实 API 要几秒
2. **可靠性**：不依赖网络和 API 服务可用性
3. **成本**：测试 100 次也不花一分钱
4. **确定性**：模拟 Provider 返回固定内容，容易验证

---

## 9. 项目结构与文件说明

```
mewcode/
│
├── mewcode.yml              # <-- 你要编辑的文件：配置 AI 厂商信息
├── pyproject.toml            # Python 项目配置（依赖、版本等）
├── README.md                 # 项目说明文档
│
└── mewcode/                  # 源代码目录
    │
    ├── __init__.py           # 包初始化（写了版本号 0.1.0）
    ├── __main__.py           # 让 "python -m mewcode" 能运行
    ├── main.py               # 程序入口：读取配置→启动界面
    │
    ├── config/               # 📁 配置相关
    │   ├── __init__.py
    │   ├── schema.py         # 定义 ProviderConfig（配置的格式模板）
    │   └── loader.py         # 读取 YAML 文件、检查配置是否完整
    │
    ├── providers/            # 📁 AI 厂商适配
    │   ├── __init__.py
    │   ├── base.py           # 抽象基类（所有厂商必须遵守的规范）
    │   ├── anthropic.py      # Anthropic Claude 的适配器
    │   ├── openai.py         # OpenAI 的适配器
    │   └── factory.py        # 工厂（根据配置自动创建对应的适配器）
    │
    ├── session/              # 📁 会话管理
    │   ├── __init__.py
    │   └── chat.py           # 聊天会话（记忆历史、编排请求）
    │
    └── tui/                  # 📁 终端界面
        ├── __init__.py
        ├── app.py            # Textual App（应用主入口）
        ├── css/
        │   └── app.tcss      # 样式文件（颜色、大小、间距）
        ├── screens/
        │   ├── chat_screen.py    # 主聊天页面
        │   └── provider_select.py  # 选择 AI 厂商的页面
        └── widgets/
            ├── banner.py         # 顶部猫咪横幅
            ├── input_box.py      # 底部输入框
            ├── message_list.py   # 消息列表
            ├── message_bubble.py # 单条消息气泡
            ├── status_bar.py     # 底部状态栏
            └── timer_indicator.py # 响应计时器
```

---

## 10. 配置与使用方法

### 10.1 配置 AI 厂商

编辑 `mewcode.yml` 文件（跟 `mewcode/` 文件夹在同一个目录）：

```yaml
providers:
  - name: my-claude                  # 给这个配置起个名字
    protocol: anthropic               # 厂商类型：anthropic 或 openai
    model: claude-sonnet-5-20251001   # 模型名
    base_url: https://api.anthropic.com  # API 地址
    api_key: sk-ant-your-key-here     # 你的密钥（保密！）
    thinking: false                   # 是否开启深度思考（可选）

  - name: my-openai
    protocol: openai
    model: gpt-4o
    base_url: https://api.openai.com
    api_key: sk-your-key-here
```

**如果你只有一个厂商：** 只写一个，启动后直接进入对话。
**如果有多个：** 启动后会出现一个列表，用方向键选择。

### 10.2 启动

```bash
cd /c/Users/Zhouyuhang/Desktop/mewcode
python -m mewcode
```

### 10.3 操作方式

| 操作 | 方法 |
|------|------|
| 发送消息 | 输入文字后按 **Enter** |
| 换行 | **Alt+Enter**（方便写多行内容） |
| 退出 | 输入 **/exit** 或按 **Ctrl+C** |

### 10.4 注意事项

- API 密钥要保密，不要分享给别人
- 如果请求失败，程序不会退出，在对话区显示错误后可以继续问
- 聊天记录退出后不会保存（每次启动都是全新的对话）

---

## 11. 常见概念解释

### 什么是 API？

API（Application Programming Interface，应用程序编程接口）。
简单说，就是"两个程序之间约定好的沟通方式"。

AI 厂商的 API 就是：
> 你按特定格式发一个 HTTP 请求过去，它按特定格式返回结果。

### 什么是 HTTP 请求？

HTTP（超文本传输协议）是互联网上最基础的通信协议。
你在浏览器打开网页时，浏览器就是在发 HTTP 请求。

AI 的 API 调用本质上也一样——只不过请求和返回的内容不是 HTML 网页，
而是结构化的 JSON 数据。

### 什么是 JSON？

JSON（JavaScript Object Notation）是一种数据格式，长这样：

```json
{
  "name": "MewCode",
  "version": "0.1.0",
  "features": ["chat", "streaming"]
}
```

它的意思是：
- 有一个对象（`{}`）
- 里面有 `name` 属性，值是 "MewCode"
- 有 `version` 属性，值是 "0.1.0"
- 有 `features` 属性，值是一个列表

### 什么是异步（async/await）？

同步执行：你做饭，等水烧开了才切菜，等切完菜才炒菜。
异步执行：你烧上水，同时切菜，同时炒菜——谁准备好了就处理谁。

Python 的 `async/await` 就是用来写异步代码的。
我们的程序需要在等待 AI 回复的同时，界面还能响应（可以滚动、显示计时器更新）。

### 什么是 SSE？

SSE（Server-Sent Events，服务器推送事件）。
普通 HTTP 请求是「你问一句，服务器回一句」。
SSE 是「你问一句，服务器可以不停地发很多句」，就像广播一样。

AI 流式回复就是通过 SSE 实现的。

### 什么是 TUI？

TUI（Textual User Interface，文本用户界面）。
就是运行在终端里的图形界面，用字符画出来的按钮、输入框、列表等。

相比于 GUI（图形用户界面，如微信、Chrome），TUI 更轻量，
不需要图形系统，在任何终端里都能跑。

### 什么是面向对象编程（OOP）？

面向对象编程是一种写代码的方式。核心思想：

> 把相关的数据和功能打包在一起，叫"对象"（Object）。

比如 `ChatSession` 这个对象：
- **数据**：`history`（聊天历史）
- **功能**：`add_message()`（添加消息）、`request()`（发起请求）

面向对象的三大好处：
1. **封装**：`ChatSession` 内部怎么存历史的，外面不用管
2. **继承**：`AnthropicProvider` 继承自 `LLMProvider`，自动获得接口规范
3. **多态**：不管是 Anthropic 还是 OpenAI，外面调用时都是 `provider.chat_stream()`

### 什么是设计模式？

设计模式是**常见问题的标准解决方案**，就像菜谱：

- 「想做红烧肉」→ 有红烧肉的做法
- 「想根据配置动态创建对象」→ 用**工厂模式**

我们用的工厂模式：
```python
# 不用工厂的写法：
if config.protocol == "anthropic":
    provider = AnthropicProvider(config)
elif config.protocol == "openai":
    provider = OpenAIProvider(config)

# 用工厂的写法：
provider = ProviderFactory.create(config)  # 一行搞定
```

工厂的好处：加新厂商时只需注册 class，不用改调用处的代码。

---

## 12. 后续可以做什么

以下功能是这期明确**不做**的，后续可以逐步加上：

**功能增强：**
1. **工具调用 / Function Calling** — 让 AI 能执行代码、操作文件
2. **文件操作与代码编辑** — AI 能直接修改你的代码文件
3. **MCP 集成** — 连接外部工具和服务

**体验优化：**
4. **上下文压缩** — 聊天太长时自动摘要或截断，节省 token
5. **slash 命令** — 添加 /help、/clear、/model 等命令
6. **流式中断** — 按某个键能取消正在生成的回复

**展示增强：**
7. **thinking 内容折叠** — 把 Claude 的思考过程用折叠方式展示出来
8. **用量统计** — 显示每次对话用了多少 token、花了多少钱

**持久化：**
9. **聊天记录保存** — 退出后下次启动还能继续之前的对话

**技术债务：**
10. **自动重试** — 网络波动时自动重试几次再报错
11. **配置热加载** — 改了配置文件不用重启就能生效

---

> 本文档由 Claude Code (mew-spec 流程) 于 2026-07-28 生成。
>
> 如果在使用中遇到任何问题，随时可以问我！
