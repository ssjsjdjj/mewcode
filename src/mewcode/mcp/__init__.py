"""MCP 客户端（docs/ch07）：配置加载、连接管理、远端工具适配。

对外暴露 Config / ServerConfig / Manager / McpTool / load_config / new_manager。
"""

from .config import Config, ServerConfig, load_config
from .manager import Manager, new_manager
from .tool import McpTool

__all__ = ["Config", "ServerConfig", "Manager", "McpTool", "load_config", "new_manager"]
