"""协议默认上下文窗口常量（docs/ch08 T24）。

默认值定义在 config 自身，不放 compact 包，避免 config → compact 反向依赖。
"""

DEFAULT_ANTHROPIC_CONTEXT_WINDOW = 200000
DEFAULT_OPENAI_CONTEXT_WINDOW = 128000
