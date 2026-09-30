"""
mcp_protocol_probe.py
"裸协议"探针：不经 LangChain、不涉及大模型，直接用官方 mcp SDK 和
mcp_weather_server.py 对话，把 MCP 的握手与工具调用原样打印出来。

它就是 MCP 客户端最基本的三步（看懂这三步，MCP 就懂了一大半）：
    1) initialize  建连接 + 协商协议版本；拿到 server_info / capabilities / protocol_version
    2) tools/list  拿到服务端暴露的工具清单，含 input_schema —— 给模型看的"函数签名"
    3) tools/call  真正调用工具，读回 content（给模型看的文本块）
                   与 structured_content（给程序用的 JSON）、is_error（工具是否失败）

对照关系：
    LangChain 侧看到的 Tool(name/description/args) ← 就是 tools/list 的产物
    模型决定调用工具后发出的 tool_calls             ← 就是 tools/call 的请求

用法：
    pip install "mcp>=2"
    python mcp_protocol_probe.py            # 默认查"上海"
    python mcp_protocol_probe.py 北京        # 指定城市
不需要 ZHIPU_API_KEY。

注意（官方文档明确写了）：stdio 传输下客户端拉起的子进程**不会继承你的全部环境变量**，
它只拿到一份白名单（HOME/PATH/SHELL/TERM 等）。本示例的服务端不需要任何环境变量，
所以这里不传 env=；若你的服务端需要 API Key，请用 StdioServerParameters(env={...}) 显式传入。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 输出中文时避免在 GBK 终端下崩掉（这里只影响本探针自己的 stdout）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
SERVER_SCRIPT = BASE_DIR / "mcp_weather_server.py"
PYTHON_BIN = os.environ.get("MCP_PYTHON", sys.executable)
TOOL_NAME = "get_current_weather"

LINE = "=" * 72


def section(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")


def _schema_of(tool) -> dict:
    """v2 是 input_schema，v1 是 inputSchema，两个都兼容。"""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


def _is_error(result):
    value = getattr(result, "is_error", None)
    if value is None:
        value = getattr(result, "isError", None)
    return value


def _structured(result):
    value = getattr(result, "structured_content", None)
    if value is None:
        value = getattr(result, "structuredContent", None)
    return value


def print_tool(tool) -> None:
    title = getattr(tool, "title", None)
    print(f"  名称        : {getattr(tool, 'name', '?')}")
    print(f"  标题        : {title}")
    print(f"  描述        : {(getattr(tool, 'description', '') or '').strip()}")
    print("  input_schema: " + json.dumps(_schema_of(tool), ensure_ascii=False, indent=4))


def print_result(result) -> None:
    print(f"  is_error          : {_is_error(result)}")
    print("  content（给模型看的文本块）:")
    for block in getattr(result, "content", []) or []:
        kind = getattr(block, "type", type(block).__name__)
        print(f"      [{kind}] {getattr(block, 'text', block)}")
    structured = _structured(result)
    print("  structured_content（给程序用的 JSON）: "
          + (json.dumps(structured, ensure_ascii=False) if structured is not None else "None"))


# ---------------------------------------------------------------------------
# mcp >= 2：from mcp import Client
# ---------------------------------------------------------------------------
async def probe_v2(params, city: str) -> None:
    from mcp import Client

    # Client(StdioServerParameters) 会被解析成 stdio 传输：进入 async with 时拉起子进程，
    # 退出时自动关掉（关 stdin → 等待 → 需要时 kill），不用你手动清理。
    async with Client(params) as client:
        section("[1/3] initialize 之后，客户端看到的连接事实")
        print(f"  server_info        : {client.server_info}")
        print(f"  protocol_version   : {client.protocol_version}")
        print(f"  server_capabilities: {client.server_capabilities}")

        section("[2/3] tools/list —— 服务端暴露的工具清单")
        listed = await client.list_tools()
        for tool in listed.tools:
            print_tool(tool)
            print("  " + "-" * 68)

        section(f"[3/3] tools/call —— 调用 {TOOL_NAME}(city={city!r})")
        result = await client.call_tool(TOOL_NAME, {"city": city})
        print_result(result)


# ---------------------------------------------------------------------------
# mcp 1.x：ClientSession + stdio_client（旧写法，属性名是 camelCase）
# ---------------------------------------------------------------------------
async def probe_v1(params, city: str) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            section("[1/3] initialize 之后，客户端看到的连接事实")
            init = await session.initialize()
            print(f"  serverInfo       : {init.serverInfo}")
            print(f"  protocolVersion  : {init.protocolVersion}")
            print(f"  capabilities     : {init.capabilities}")

            section("[2/3] tools/list —— 服务端暴露的工具清单")
            listed = await session.list_tools()
            for tool in listed.tools:
                print_tool(tool)
                print("  " + "-" * 68)

            section(f"[3/3] tools/call —— 调用 {TOOL_NAME}(city={city!r})")
            result = await session.call_tool(TOOL_NAME, {"city": city})
            print_result(result)


async def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "上海"

    if not SERVER_SCRIPT.is_file():
        raise SystemExit(f"找不到服务端脚本：{SERVER_SCRIPT}")

    from mcp import StdioServerParameters  # v1 / v2 都能从这里导入

    params = StdioServerParameters(
        command=PYTHON_BIN,
        args=[str(SERVER_SCRIPT)],
        # 服务端不需要环境变量；若需要，在这里用 env={"KEY": "VALUE"} 显式传入
    )

    print(f"启动命令   : {PYTHON_BIN} {SERVER_SCRIPT}")
    print("传输方式   : stdio（子进程的 stdin/stdout 就是协议线）")
    print(f"查询城市   : {city}")

    try:
        from mcp import Client  # noqa: F401  mcp>=2 才有这个高层 Client

        sdk_flavor = "mcp>=2（mcp.Client）"
        probe = probe_v2
    except ImportError:
        sdk_flavor = "mcp 1.x（ClientSession + stdio_client）"
        probe = probe_v1

    print(f"SDK 分支   : {sdk_flavor}")
    await probe(params, city)
    print(f"\n{LINE}\n完成：以上三步就是 MCP 客户端与 Server 的全部交互。\n{LINE}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n[中断] 用户取消。", file=sys.stderr)
        raise SystemExit(130)
