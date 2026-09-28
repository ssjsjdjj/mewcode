"""配置层（docs/ch02 T2；ch08 T24 由单模块拆分为包）。

对外 API 与原单模块一致：load / ConfigError / ProviderConfig / Config /
effective_context_window，现有调用方无需改动 import。
"""

from .config import (
    VALID_PROTOCOLS,
    Config,
    ConfigError,
    ProviderConfig,
    effective_context_window,
    load,
)
from .protocol_defaults import (
    DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
    DEFAULT_OPENAI_CONTEXT_WINDOW,
)

__all__ = [
    "VALID_PROTOCOLS",
    "Config",
    "ConfigError",
    "DEFAULT_ANTHROPIC_CONTEXT_WINDOW",
    "DEFAULT_OPENAI_CONTEXT_WINDOW",
    "ProviderConfig",
    "effective_context_window",
    "load",
]
