"""ch07 AC5：HTTP 传输 + 自定义 headers（streamable http client + MockTransport）。

不拉起真实网络服务：用 httpx2.MockTransport 注入一个内存 MCP HTTP 端点，断言
(1) 握手 + tools/list 走通、工具按 `mcp__<server>__<tool>` 注册；
(2) 配置里的 `headers` 真正出现在每个请求上（server 端收到 Authorization 头）。
"""

import json

import httpx2
import pytest

from mewcode.mcp import Config, ServerConfig, new_manager


def _handler(seen: list, tools: list):
    async def handler(request):
        seen.append(dict(request.headers))
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        rid = body.get("id")
        if body.get("method") == "initialize":
            return httpx2.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "protocolVersion": "2025-11-25",  # 回显客户端提议的握手版本
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock-http", "version": "0.0.0"},
                    },
                },
            )
        if body.get("method") == "tools/list":
            return httpx2.Response(
                200,
                json={"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}},
            )
        # 通知（notifications/initialized 等）→ 202，不响应
        return httpx2.Response(202)

    return handler


@pytest.fixture
def http_client(monkeypatch):
    """把 manager 里的 httpx2.AsyncClient 换成带 MockTransport 的内存客户端。"""

    def install(handler):
        orig = httpx2.AsyncClient
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: orig(transport=httpx2.MockTransport(handler), **kw),
        )

    return install


async def test_http_headers_reach_server_and_tools_registered(http_client):
    seen: list[dict] = []
    tools = [
        {"name": "echo", "description": "回显", "inputSchema": {"type": "object"}},
        {"name": "add", "description": "加法", "inputSchema": {"type": "object"}},
    ]
    http_client(_handler(seen, tools))
    cfg = Config(
        servers={
            "http-demo": ServerConfig(
                type="http",
                url="http://mock.local/mcp",
                headers={"Authorization": "Bearer tok123", "X-Custom": "y"},
            )
        }
    )
    mgr = await new_manager(cfg, version="dev")
    try:
        names = [t.name() for t in mgr.tools()]
        assert names == ["mcp__http-demo__add", "mcp__http-demo__echo"]
    finally:
        await mgr.close()

    assert seen, "handler 应收到至少一个 HTTP 请求"
    for headers in seen:
        assert headers.get("authorization") == "Bearer tok123"
        assert headers.get("x-custom") == "y"


async def test_http_read_only_hint(http_client):
    """http 工具带 readOnlyHint=True → read_only 为 True（适配层贯通）。"""
    seen: list[dict] = []
    tools = [
        {
            "name": "lookup",
            "description": "查询",
            "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True},
        }
    ]
    http_client(_handler(seen, tools))
    cfg = Config(servers={"http-demo": ServerConfig(type="http", url="http://mock.local/mcp")})
    mgr = await new_manager(cfg, version="dev")
    try:
        tools_out = mgr.tools()
        assert len(tools_out) == 1
        assert tools_out[0].read_only is True
    finally:
        await mgr.close()
