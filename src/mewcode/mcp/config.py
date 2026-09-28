"""MCP 客户端配置：两层 YAML 加载、按 server 名合并、${VAR} 展开与字段校验（docs/ch07 T2）。

用户级 `~/.mewcode/config.yaml` 与项目级 `<root>/.mewcode.yaml` 的 `mcp_servers` 段
按 server 名合并，项目级同名完整覆盖用户级。整个模块永不抛出异常：文件缺失视为空层、
格式非法只跳过该层并 stderr 告警（N1），非法 server 只剔除自身（N2）。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _warn(msg: str) -> None:
    """统一的 stderr 告警前缀，供降级 / 跳过场景使用。"""
    print(f"[mcp] warn: {msg}", file=sys.stderr)


@dataclass
class ServerConfig:
    """单个 MCP server 的完整定义（已展开 ${VAR}、已校验）。"""

    type: Literal["stdio", "http"]
    command: str = ""  # stdio 必填
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""  # http 必填
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """mcp_servers 在内存中的归一化形式（已合并、已剔除非法 server）。"""

    servers: dict[str, ServerConfig] = field(default_factory=dict)


@dataclass
class _RawServer:
    """配置文件里一个 server 的原始定义（字段全部可选，待展开 / 校验）。"""

    type: Any = None
    command: Any = None
    args: Any = None
    env: Any = None
    url: Any = None
    headers: Any = None


def load_config(root: str) -> Config:
    """加载两层配置并合并；永不抛出（文件缺失 / 非法 / server 非法均降级）。"""
    try:
        user_path = Path.home() / ".mewcode" / "config.yaml"
        user = _load_layer(user_path)
    except Exception:  # noqa: BLE001 —— Path.home() 失败时跳过用户层，不致错
        user = {}
    project = _load_layer(Path(root) / ".mewcode.yaml")

    merged = _merge_servers(user, project)
    servers: dict[str, ServerConfig] = {}
    for name, raw in merged.items():
        validated = _validate_server(name, raw)
        if validated is not None:
            servers[name] = validated
    return Config(servers=servers)


def _load_layer(path: Path) -> dict[str, _RawServer]:
    """加载单层文件并对其内 server 做 ${VAR} 展开。"""
    servers = _load_file(path)
    for name, srv in servers.items():
        _apply_expansion(name, srv)
    return servers


def _load_file(path: Path) -> dict[str, _RawServer]:
    """读取单个配置文件，返回 `mcp_servers` 段的原始映射。

    文件不存在、读取 / YAML 解析失败、结构非法 → 告警一行并返回空 dict（调用方降级）。
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 任何读取/解析失败都降级为空层（N1）
        _warn(f"load {path} failed: {exc}")
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        _warn(f"load {path} failed: 顶层必须是对象")
        return {}
    servers_raw = data.get("mcp_servers")
    if servers_raw is None:
        return {}
    if not isinstance(servers_raw, dict):
        _warn(f"load {path} failed: mcp_servers 必须是对象")
        return {}

    out: dict[str, _RawServer] = {}
    for sname, item in servers_raw.items():
        if not isinstance(item, dict):
            _warn(f"skip server {sname}: 定义必须是对象")
            continue
        out[str(sname)] = _RawServer(
            type=item.get("type"),
            command=item.get("command"),
            args=item.get("args"),
            env=item.get("env"),
            url=item.get("url"),
            headers=item.get("headers"),
        )
    return out


def _expand_vars(s: str) -> tuple[str, list[str]]:
    """展开字符串中的全部 `${VAR}`；返回 (展开结果, 未定义变量名列表)。"""
    undefined: list[str] = []

    def repl(m: re.Match[str]) -> str:
        var = m.group(1)
        if var not in os.environ:
            undefined.append(var)
            return ""
        return os.environ[var]

    return _VAR_RE.sub(repl, s), undefined


def _apply_expansion(name: str, srv: _RawServer) -> None:
    """对 env / headers 的值做 ${VAR} 展开（原地替换）；未定义变量告警一次/个。"""
    for field_name in ("env", "headers"):
        mapping = getattr(srv, field_name)
        if not isinstance(mapping, dict):
            continue
        undefined: set[str] = set()
        for key, value in mapping.items():
            if not isinstance(value, str):
                continue
            expanded, undef = _expand_vars(value)
            mapping[key] = expanded
            undefined.update(undef)
        for var in sorted(undefined):
            _warn(f"undefined env var ${{{var}}} referenced by server {name}")


def _merge_servers(
    user: dict[str, _RawServer], project: dict[str, _RawServer]
) -> dict[str, _RawServer]:
    """按 server 名合并：项目级同名完整覆盖用户级（不做字段级合并）。"""
    merged = dict(user)
    merged.update(project)
    return merged


def _validate_server(name: str, srv: _RawServer) -> ServerConfig | None:
    """校验单个 server；非法则告警并返回 None（不静默放行未定义 server）。"""
    if srv.type not in ("stdio", "http"):
        _warn(f"skip server {name}: type 必须为 stdio 或 http")
        return None
    if srv.type == "stdio" and not (isinstance(srv.command, str) and srv.command.strip()):
        _warn(f"skip server {name}: stdio 类型必须提供 command")
        return None
    if srv.type == "http" and not (isinstance(srv.url, str) and srv.url.strip()):
        _warn(f"skip server {name}: http 类型必须提供 url")
        return None

    args = (
        [a for a in srv.args]
        if isinstance(srv.args, list) and all(isinstance(a, str) for a in srv.args)
        else []
    )
    env = (
        {k: v for k, v in srv.env.items()}
        if isinstance(srv.env, dict) and all(isinstance(v, str) for v in srv.env.values())
        else {}
    )
    headers = (
        {k: v for k, v in srv.headers.items()}
        if isinstance(srv.headers, dict) and all(isinstance(v, str) for v in srv.headers.values())
        else {}
    )
    return ServerConfig(
        type=srv.type,  # srv.type 已确认是 "stdio"/"http"（Any → Literal 赋值合法）
        command=srv.command or "",
        args=args,
        env=env,
        url=srv.url or "",
        headers=headers,
    )
