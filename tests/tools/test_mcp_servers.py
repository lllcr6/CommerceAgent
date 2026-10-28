import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient

pytestmark = pytest.mark.integration

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"MCP Server 端口 {port} 在 {timeout}s 内未就绪")


@pytest.fixture(scope="module")
def mcp_procs():
    p1 = subprocess.Popen([sys.executable, str(_ROOT / "mcp_servers/logistics_server.py")],
                          env={**os.environ, "PORT": "18101"})
    p2 = subprocess.Popen([sys.executable, str(_ROOT / "mcp_servers/aftersales_server.py")],
                          env={**os.environ, "PORT": "18102"})
    try:
        _wait_port(18101)
        _wait_port(18102)
        yield
    finally:
        p1.terminate()
        p2.terminate()
        p1.wait(timeout=5)
        p2.wait(timeout=5)


def _client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "logistics": {"transport": "streamable_http", "url": "http://127.0.0.1:18101/mcp"},
        "aftersales": {"transport": "streamable_http", "url": "http://127.0.0.1:18102/mcp"},
    }, handle_tool_errors=False)


async def test_list_tools_three_essentials(mcp_procs):
    tools = await _client().get_tools()
    by = {t.name: t for t in tools}
    assert set(by) == {"query_logistics", "query_warranty", "query_return_status"}
    for t in by.values():
        assert t.description
        schema = t.args_schema if isinstance(t.args_schema, dict) else t.args_schema.model_json_schema()
        assert schema.get("properties")


def _text_of(result) -> str:

    if isinstance(result, list):
        return "\n".join(b.get("text", "") for b in result if isinstance(b, dict))
    return str(result)


async def test_invoke_logistics_stable_mock(mcp_procs):
    tools = {t.name: t for t in await _client().get_tools(server_name="logistics")}
    r1 = await tools["query_logistics"].ainvoke({"tracking_no": "SF123"})
    r2 = await tools["query_logistics"].ainvoke({"tracking_no": "SF123"})
    assert _text_of(r1) == _text_of(r2)
    assert "status_code" in _text_of(r1)
