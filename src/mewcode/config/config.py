"""配置加载与校验（docs/ch02 T2；ch08 T24 拆分为 config 包并追加 context_window）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from .protocol_defaults import (
    DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
    DEFAULT_OPENAI_CONTEXT_WINDOW,
)

VALID_PROTOCOLS = ("anthropic", "openai")


class ConfigError(Exception):
    """配置错误，message 为面向用户的可读信息。"""


@dataclass
class ProviderConfig:
    name: str
    protocol: Literal["anthropic", "openai"]
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False
    context_window: int = 0  # 0 表示未配置，用协议默认值


def effective_context_window(p: ProviderConfig) -> int:
    """解析有效上下文窗口：显式配置 > 0 用之；否则按协议取默认。

    未知协议保守退回 anthropic 默认值。
    """
    if p.context_window > 0:
        return p.context_window
    if p.protocol == "openai":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW


@dataclass
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)


def load(path: str) -> Config:
    """读取并校验配置文件。失败抛 ConfigError（含具体位置与字段）。"""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 YAML 解析失败: {exc}") from exc
    return _from_dict(raw)


def _from_dict(raw: object) -> Config:
    if not isinstance(raw, dict) or "providers" not in raw:
        raise ConfigError("配置文件必须包含顶层键 providers（列表）")
    providers_raw = raw["providers"]
    if not isinstance(providers_raw, list) or not providers_raw:
        raise ConfigError("providers 不能为空，至少配置一个 provider")

    providers: list[ProviderConfig] = []
    for i, item in enumerate(providers_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"providers[{i}] 必须是对象")

        def req(field_name: str) -> str:
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"providers[{i}].{field_name} 不能为空")
            return value.strip()

        name = req("name")
        protocol = req("protocol")
        if protocol not in VALID_PROTOCOLS:
            raise ConfigError(f"providers[{i}].protocol 必须是 anthropic 或 openai")
        api_key = req("api_key")
        model = req("model")

        base_url = item.get("base_url")
        if base_url is not None and not isinstance(base_url, str):
            raise ConfigError(f"providers[{i}].base_url 必须是字符串")

        thinking = item.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"providers[{i}].thinking 必须是布尔值")

        context_window = item.get("context_window", 0)
        if not isinstance(context_window, int):
            context_window = 0  # 非法值按未配置处理，用协议默认

        providers.append(
            ProviderConfig(
                name=name,
                protocol=protocol,
                api_key=api_key,
                model=model,
                base_url=base_url,
                thinking=thinking,
                context_window=context_window,
            )
        )
    return Config(providers=providers)
