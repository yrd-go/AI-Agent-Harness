"""
mcp_weather_server.py
最小 MCP Server 示例：用官方 mcp Python SDK 暴露一个 get_current_weather 工具。

MCP（Model Context Protocol）里，Server 负责"提供能力"，Client（这里是 LangChain）
负责"把能力交给模型调用"。本文件用 stdio 传输：客户端把本文件当成子进程拉起，
通过它的 stdin/stdout 交换 JSON-RPC 报文。

三条必须记住的规则（stdio 传输特有）：
    1. stdout 就是协议线。服务端里绝对不能用 print() 输出任何东西，
       否则报文被污染，客户端会直接解析失败。要日志就用 logging（默认走 stderr）。
    2. run() 必须放在 if __name__ == "__main__": 里面。mcp dev / mcp run /
       客户端拉子进程都会先 import 这个文件，没有守卫就会在导入时把服务器跑起来。
    3. 工具的 docstring + 类型标注（这里的 city: str）会被 SDK 自动转成 JSON Schema，
       这正是 tools/list 返回给模型看的"函数签名"，也是模型能正确填参数的原因。

兼容性：优先用 mcp>=2 的 MCPServer；装的是 mcp 1.x 时自动回退到 FastMCP。

安装：
    pip install "mcp>=2"          # 新版（推荐）
    pip install "mcp>=1.28,<2"    # 旧版也能跑，代码会自动回退

单独运行（stdio 服务端没有端口；直接跑会"卡住不输出"，那是在等 stdin，Ctrl+C 退出）：
    python mcp_weather_server.py

可视化调试（需要 Node/npx，会起 MCP Inspector，能点点看工具）：
    mcp dev mcp_weather_server.py
"""
from __future__ import annotations

import logging
import sys

# ---------------------------------------------------------------------------
# 0. stderr 编码守卫
#    只动 stderr —— stdout 是协议线，一个字都不能碰。
#    必须早于 MCPServer 构造：它的构造函数内部会调用 logging.basicConfig()。
# ---------------------------------------------------------------------------
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 1. 兼容 mcp v2 与 v1 的服务端类（同一份代码两种 SDK 都能跑）
# ---------------------------------------------------------------------------
try:
    from mcp.server import MCPServer as _ServerBase  # mcp >= 2

    SDK_FLAVOR = "mcp>=2（mcp.server.MCPServer）"
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerBase

    SDK_FLAVOR = "mcp 1.x（mcp.server.fastmcp.FastMCP）"

mcp = _ServerBase("weather-demo")

logger = logging.getLogger("weather-demo")

# ---------------------------------------------------------------------------
# 2. 模拟数据（真实项目里这里换成气象 API 调用即可，协议层完全不用改）
# ---------------------------------------------------------------------------
MOCK_WEATHER = {
    "北京": "晴，25度（北风 3 级，湿度 40%）",
    "上海": "晴，25度（东南风 2 级，湿度 60%）",
    "广州": "多云，29度（南风 2 级，湿度 75%）",
    "深圳": "阵雨，28度（东风 3 级，湿度 80%）",
    "杭州": "阴，24度（微风，湿度 65%）",
}

# 顺手支持拼音输入，演示"工具内部可以随便做参数归一化"
CITY_ALIASES = {
    "beijing": "北京",
    "shanghai": "上海",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hangzhou": "杭州",
}


# ---------------------------------------------------------------------------
# 3. 唯一的工具：@mcp.tool() 之后，函数签名 + docstring 就是对外契约
# ---------------------------------------------------------------------------
@mcp.tool()
def get_current_weather(city: str) -> str:
    """查询指定城市当前的天气情况。

    参数：
        city: 城市名称，中文或拼音均可，例如 "上海" 或 "shanghai"。

    返回：
        一句中文天气描述，例如 "上海：晴，25度（东南风 2 级，湿度 60%）"。
    """
    raw = (city or "").strip()
    if not raw:
        return "未提供城市名：请告诉我要查哪个城市，例如“上海”。"

    name = CITY_ALIASES.get(raw.lower(), raw)
    detail = MOCK_WEATHER.get(name)
    if detail is None:
        detail = (
            f"暂无该城市的天气数据（这是演示服务，只内置了 "
            + "、".join(MOCK_WEATHER)
            + " 的模拟数据）。"
        )

    result = f"{name}：{detail}"
    # 日志走 stderr，绝不影响 stdout 上的 JSON-RPC 报文
    logger.info("tools/call get_current_weather(city=%r) -> %s", city, result)
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[server] %(levelname)s %(message)s",
    )
    logger.info("weather-demo MCP Server 启动中（%s，stdio 传输）", SDK_FLAVOR)
    # run() 不带参数 = stdio 传输，客户端会以子进程方式连上来。
    # 想部署成 HTTP 服务：mcp.run(transport="streamable-http", port=8000)，
    # 客户端则改成连 http://127.0.0.1:8000/mcp 。
    mcp.run()
