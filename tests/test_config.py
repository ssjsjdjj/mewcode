"""config 模块单测（docs/ch02 T2）。"""

import textwrap
from pathlib import Path

import pytest

from mewcode.config import ConfigError, ProviderConfig, effective_context_window, load


def write_config(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_load_valid(tmp_path):
    write_config(
        tmp_path / "config.yaml",
        """
        providers:
          - name: a
            protocol: anthropic
            api_key: k1
            model: m1
          - name: b
            protocol: openai
            api_key: k2
            model: m2
            base_url: http://x
            thinking: true
        """,
    )
    cfg = load(str(tmp_path / "config.yaml"))
    assert len(cfg.providers) == 2
    assert cfg.providers[0].name == "a"
    assert cfg.providers[1].thinking is True
    assert cfg.providers[1].base_url == "http://x"


def test_missing_field(tmp_path):
    write_config(
        tmp_path / "config.yaml",
        """
        providers:
          - name: a
            protocol: anthropic
            model: m1
        """,
    )
    with pytest.raises(ConfigError, match="api_key"):
        load(str(tmp_path / "config.yaml"))


def test_invalid_protocol(tmp_path):
    write_config(
        tmp_path / "config.yaml",
        """
        providers:
          - name: a
            protocol: foo
            api_key: k
            model: m1
        """,
    )
    with pytest.raises(ConfigError, match="protocol"):
        load(str(tmp_path / "config.yaml"))


def test_file_missing(tmp_path):
    with pytest.raises(ConfigError, match="不存在"):
        load(str(tmp_path / "config.yaml"))


def test_effective_context_window_unconfigured():
    p = ProviderConfig(name="a", protocol="anthropic", api_key="k", model="m")
    assert effective_context_window(p) == 200000


def test_effective_context_window_zero():
    p = ProviderConfig(name="a", protocol="openai", api_key="k", model="m", context_window=0)
    assert effective_context_window(p) == 128000


def test_effective_context_window_positive():
    p = ProviderConfig(name="a", protocol="anthropic", api_key="k", model="m", context_window=80000)
    assert effective_context_window(p) == 80000


def test_effective_context_window_unknown_protocol():
    p = ProviderConfig(name="a", protocol="mystery", api_key="k", model="m")
    assert effective_context_window(p) == 200000  # 保守退回 anthropic 默认


def test_yaml_error(tmp_path):
    (tmp_path / "config.yaml").write_text("providers: [bad", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load(str(tmp_path / "config.yaml"))
