"""项目指令文件加载（docs/ch09 F1-F8）。

三层 MEWCODE.md 按优先级加载 + @include 展开，供系统提示 custom-instructions
模块注入。见 loader.Loader。
"""

from .loader import Loader

__all__ = ["Loader"]
