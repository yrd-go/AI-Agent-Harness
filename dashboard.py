# -*- coding: utf-8 -*-
"""
web_demo/dashboard.py —— 统一 Web 控制台（Streamlit 单文件）
===================================================================

把现有 4 个核心脚本收拢到一个网页控制台，前后端不分离（纯 Streamlit）：

    ① RAG 知识库问答      -> subprocess 调用 rag_demo.py
    ② 多智能体协作演示    -> subprocess 调用 multi_agent_demo.py（无参数）
    ③ 多模型路由          -> subprocess 调用 router.py "<自然语言指令>"
    ④ MCP 协议探针        -> subprocess 调用 mcp_protocol_probe.py [城市]

设计原则（与需求一一对应）：
  1. 后端不硬编码任何业务逻辑：页面只负责拼命令行参数，真正的逻辑仍在原脚本里。
  2. 统一执行器 run_python()：subprocess.run(capture_output=True, text=True,
     encoding="utf-8", errors="replace", timeout=..., env=child_env)，
     其中 child_env 注入 PYTHONIOENCODING=utf-8（外加 PYTHONUTF8=1 /
     PYTHONUNBUFFERED=1）——这是根治 Windows 下子进程中文乱码的关键。
  3. stdout 用 st.code 展示，stderr 收进 expander，退出码用成功/失败提示。
  4. 超时（默认 120s，模块四硬上限 30s）与各种 OSError 一律转成友好提示，
     网页绝不打 traceback 崩溃、绝不一直转圈。
  5. 每个模块都有「清空输出」按钮（侧边栏另有「清空全部输出」）。
  6. 安全：只做 os.environ 透传；本文件不读取、不打印、不回显 .env 的任何内容，
     也不输出任何 API Key。

模块四的安全约束（重要）：
    只允许调用 mcp_protocol_probe.py，**绝对不要**调用 mcp_weather_client.py。
    探针脚本自己管理 mcp_weather_server.py 子进程的 stdio 生命周期；
    而客户端脚本走异步长连接，放进 Web 请求里极易 stdio 协议污染 + 异步死锁，
    会让页面卡死。客户端脚本继续留在终端里演示。

运行环境（本机）：
    这三个脚本的依赖（langchain / langgraph / chromadb / pymongo）都装在
    .venv-rag（Python 3.12）里，所以控制台默认优先使用 .venv-rag 的解释器。

本机运行：
    .\.venv-rag\Scripts\python.exe -m pip install streamlit
    .\.venv-rag\Scripts\python.exe -m streamlit run web_demo\dashboard.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent      # 项目根目录（本文件在 web_demo/ 下）
SCRIPT_RAG = "rag_demo.py"
SCRIPT_AGENT = "multi_agent_demo.py"
SCRIPT_ROUTER = "router.py"
SCRIPT_MCP_PROBE = "mcp_protocol_probe.py"

DEFAULT_TIMEOUT = 120          # 秒：与需求一致
MCP_TIMEOUT_CAP = 30           # 秒：模块四硬上限，防止 MCP 服务端等不到 stdin 一直转圈

# session_state 里存放各模块执行结果的键
KEY_RAG = "result_rag"
KEY_AGENT = "result_agent"
KEY_ROUTER = "result_router"
KEY_MCP = "result_mcp"
ALL_RESULT_KEYS = (KEY_RAG, KEY_AGENT, KEY_ROUTER, KEY_MCP)

st.set_page_config(page_title="Agent 统一控制台", page_icon="🧭", layout="wide")


# ===========================================================================
# 1) Python 解释器探测
#    优先级：.venv-rag > .venv > 当前解释器（Windows 与 POSIX 布局都兼容）
# ===========================================================================
INTERPRETER_CANDIDATES = (
    ".venv-rag/Scripts/python.exe",
    ".venv/Scripts/python.exe",
    ".venv-rag/bin/python",
    ".venv/bin/python",
)


def detect_interpreters() -> list[Path]:
    found: list[Path] = []
    for rel in INTERPRETER_CANDIDATES:
        p = BASE_DIR / rel
        if p.is_file() and p not in found:
            found.append(p)
    current = Path(sys.executable)
    if current not in found:
        found.append(current)
    return found


@st.cache_data(show_spinner=False)
def interpreter_version(python_path: str) -> str:
    """取解释器版本号用于展示；失败时返回空串，不影响使用。"""
    try:
        proc = subprocess.run(
            [python_path, "-c", "import sys;print(sys.version.split()[0])"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


# ===========================================================================
# 2) 统一执行层：所有子进程都从这里走
# ===========================================================================
@dataclass
class RunResult:
    script: str
    cmd: list = field(default_factory=list)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout: int = 0
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.error and self.returncode == 0


def _as_text(value) -> str:
    """subprocess 超时异常里可能带 bytes，统一转成 str。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _quote(part: str) -> str:
    return f'"{part}"' if (" " in part or "\t" in part) else part


def run_python(script_name: str, args: list, timeout: int, python_bin: Path) -> RunResult:
    """执行 BASE_DIR 下的某个脚本，抓取 stdout + stderr，任何异常都不外抛。"""
    script_path = BASE_DIR / script_name
    res = RunResult(
        script=script_name,
        cmd=[str(python_bin), str(script_path), *[str(a) for a in args]],
        timeout=int(timeout),
    )

    if not script_path.is_file():
        res.error = f"找不到脚本文件：{script_path}"
        return res
    if not Path(python_bin).is_file():
        res.error = f"找不到 Python 解释器：{python_bin}"
        return res

    # ---- 关键：复制系统环境并强制子进程以 UTF-8 输出，从根因上修复 Windows 乱码 ----
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONUNBUFFERED"] = "1"   # 让日志实时落盘，顺序更接近真实执行顺序

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            res.cmd,
            cwd=str(BASE_DIR),            # 固定工作目录，脚本里的相对路径行为可预期
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=res.timeout,
            shell=False,
        )
        res.returncode = proc.returncode
        res.stdout = proc.stdout or ""
        res.stderr = proc.stderr or ""

    except subprocess.TimeoutExpired as exc:
        # 子进程已被 subprocess 杀掉；这里只负责给出友好提示，网页不崩
        res.timed_out = True
        res.stdout = _as_text(getattr(exc, "stdout", None))
        res.stderr = _as_text(getattr(exc, "stderr", None))
    except FileNotFoundError as exc:
        res.error = f"无法启动子进程（解释器或脚本不存在）：{exc}"
    except OSError as exc:
        res.error = f"子进程启动失败（可能是沙箱禁止创建管道）：{exc}"
    except Exception as exc:  # noqa: BLE001  兜底，绝不让页面抛异常
        res.error = f"执行时发生未预期错误：{type(exc).__name__}: {exc}"

    res.elapsed = time.perf_counter() - t0
    return res


# ===========================================================================
# 3) 结果渲染与 session_state 管理
# ===========================================================================
def clear_results(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def get_result(key: str) -> RunResult | None:
    return st.session_state.get(key)


def render_result(res: RunResult) -> None:
    st.caption("执行命令：" + " ".join(_quote(str(c)) for c in res.cmd))

    if res.error:
        st.error(f"❌ {res.error}")
        return

    if res.timed_out:
        st.error(
            f"⏱ 执行超时：{res.script} 在 {res.timeout} 秒内没有返回，已强制终止。\n\n"
            "可能原因：首次建库向量化较慢、模型接口无响应、或该脚本在等待交互输入。\n"
            "建议：在左侧把「超时时间」调大后重试（例如首次建库调到 300~600 秒）。"
        )
    elif res.ok:
        st.success(f"✅ {res.script} 执行完成（退出码 0，用时 {res.elapsed:.1f}s）")
    else:
        st.warning(
            f"⚠️ {res.script} 退出码 {res.returncode}（用时 {res.elapsed:.1f}s），"
            "请看下方 stderr 中的错误输出。"
        )

    stdout = (res.stdout or "").strip()
    if stdout:
        st.markdown("**标准输出（stdout）**")
        st.code(res.stdout, language="text")
    elif not res.timed_out:
        st.info("该脚本没有产生任何标准输出。")

    stderr = (res.stderr or "").strip()
    if stderr:
        with st.expander("stderr（错误输出）", expanded=not res.ok):
            st.code(res.stderr, language="text")


def render_result_if_any(key: str) -> None:
    res = get_result(key)
    if res is not None:
        render_result(res)


# ===========================================================================
# 4) 模块一：RAG 知识库问答（默认模块）
# ===========================================================================
def module_rag(python_bin: Path, timeout: int) -> None:
    st.subheader("① RAG 知识库问答")
    st.caption(
        "对应脚本：`rag_demo.py`（查询改写 + 向量/关键词混合检索 + 智谱与 Ollama 双引擎降级）。"
    )

    question = st.text_input(
        "你的问题",
        key="rag_question",
        placeholder="例如：我的 VPN 坏了 / 如何重置密码？ / 打印机卡纸",
    )

    c1, c2, c3 = st.columns(3)
    engine = c1.selectbox(
        "生成引擎 `--engine`", ["auto", "zhipu", "ollama"], index=0, key="rag_engine",
        help="auto=智谱优先并自动降级；zhipu=只用智谱；ollama=只用本地 Ollama",
    )
    embedder = c2.selectbox(
        "向量化 `--embedder`", ["zhipu", "ollama"], index=0, key="rag_embedder",
        help="ollama 可用于全离线链路（需要本机 ollama 已 pull nomic-embed-text）",
    )
    k = c3.number_input("返回片段数 `--k`", min_value=1, max_value=20, value=4, step=1, key="rag_k")

    keyword_weight = st.slider(
        "关键词权重 α `--keyword-weight`（final = (1-α)·向量 + α·关键词）",
        min_value=0.0, max_value=1.0, value=0.30, step=0.05, key="rag_keyword_weight",
    )

    r1, r2 = st.columns(2)
    rerank = r1.checkbox(
        "开启查询改写 + 混合检索 `--rerank`（默认开）", value=True, key="rag_rerank",
        help="取消勾选会加上 --no-rerank，退回纯向量检索，便于新旧对比",
    )
    rewrite = r2.checkbox(
        "允许 LLM 查询改写 `--rewrite`", value=True, key="rag_rewrite",
        help="需要 --rerank 生效；取消勾选会加上 --no-rewrite",
    )

    r3, r4 = st.columns(2)
    rebuild = r3.checkbox(
        "强制重建向量库 `--rebuild`", value=False, key="rag_rebuild",
        help="会先删除 ./chroma_db 再重新向量化，耗时较久，建议把超时时间调大",
    )
    show_prompt = r4.checkbox(
        "打印最终 Prompt `--show-prompt`", value=False, key="rag_show_prompt",
    )

    b1, b2, _spacer = st.columns([1, 1, 4])
    run_clicked = b1.button("▶ 开始问答", type="primary", key="rag_run")
    if b2.button("🧹 清空输出", key="rag_clear"):
        clear_results(KEY_RAG)

    if run_clicked:
        text = question.strip()
        if not text and not rebuild:
            st.warning("请输入问题；若只想重建索引，请勾选「强制重建向量库 `--rebuild`」。")
        else:
            args: list = [text] if text else []
            if not rerank:
                args.append("--no-rerank")
            elif not rewrite:
                args.append("--no-rewrite")
            if rebuild:
                args.append("--rebuild")
            if show_prompt:
                args.append("--show-prompt")
            args += ["--engine", engine, "--embedder", embedder, "--k", str(int(k))]
            if abs(keyword_weight - 0.30) > 1e-9:
                args += ["--keyword-weight", f"{keyword_weight:.2f}"]

            with st.spinner("Agent 执行中..."):
                st.session_state[KEY_RAG] = run_python(SCRIPT_RAG, args, timeout, python_bin)

    render_result_if_any(KEY_RAG)


# ===========================================================================
# 5) 模块二：多智能体协作演示（无参数）
# ===========================================================================
def module_multi_agent(python_bin: Path, timeout: int) -> None:
    st.subheader("② 多智能体协作演示")
    st.caption(
        "对应脚本：`multi_agent_demo.py`（LangGraph 状态图：Retriever ↔ Reviewer，"
        "条件边打回重试，最多 2 次后安全退出）。**该脚本不需要任何参数**，"
        "点击按钮即可运行并查看完整流转日志。"
    )

    b1, b2, _spacer = st.columns([1, 1, 4])
    run_clicked = b1.button("▶ 运行演示", type="primary", key="agent_run")
    if b2.button("🧹 清空输出", key="agent_clear"):
        clear_results(KEY_AGENT)

    if run_clicked:
        with st.spinner("Agent 执行中..."):
            st.session_state[KEY_AGENT] = run_python(SCRIPT_AGENT, [], timeout, python_bin)

    render_result_if_any(KEY_AGENT)


# ===========================================================================
# 6) 模块三：多模型路由（自然语言指令）
# ===========================================================================
ROUTER_EXAMPLES = (
    "帮我查学生2",
    "帮我翻译 你好 到日语",
    "帮我翻译 apple",
    "帮我写一段代码",
)


def module_router(python_bin: Path, timeout: int) -> None:
    st.subheader("③ 多模型路由")
    st.caption(
        "对应脚本：`router.py`（关键词命中即路由：学生查询→本地脚本零成本 / "
        "翻译→免费接口 / 代码生成→DeepSeek 大模型）。"
    )

    instruction = st.text_input(
        "自然语言指令",
        key="router_instruction",
        placeholder="例如：帮我查学生2 / 帮我翻译 你好 到日语 / 帮我写一段代码",
    )
    st.caption("可试的指令：" + " ｜ ".join(f"`{x}`" for x in ROUTER_EXAMPLES))

    b1, b2, _spacer = st.columns([1, 1, 4])
    run_clicked = b1.button("▶ 执行路由", type="primary", key="router_run")
    if b2.button("🧹 清空输出", key="router_clear"):
        clear_results(KEY_ROUTER)

    if run_clicked:
        text = instruction.strip()
        if not text:
            st.warning("请输入一条自然语言指令后再执行。")
        else:
            with st.spinner("Agent 执行中..."):
                st.session_state[KEY_ROUTER] = run_python(
                    SCRIPT_ROUTER, [text], timeout, python_bin
                )

    render_result_if_any(KEY_ROUTER)


# ===========================================================================
# 7) 模块四：MCP 协议探针（只调 mcp_protocol_probe.py）
# ===========================================================================
def module_mcp_probe(python_bin: Path, timeout: int) -> None:
    st.subheader("④ MCP 协议探针")
    st.caption(
        "对应脚本：`mcp_protocol_probe.py`（裸协议演示 MCP 客户端三步："
        "① initialize 握手 ② tools/list 工具清单 ③ tools/call 工具调用），"
        "输出里的原始 JSON 结构就是 MCP 的真实协议流程。"
    )
    st.info(
        "**安全约束**：本模块只调用 `mcp_protocol_probe.py`，"
        "**不会**调用 `mcp_weather_client.py`。\n\n"
        "原因是探针脚本自己管理 `mcp_weather_server.py` 子进程的 stdio 生命周期，"
        "而客户端脚本走异步长连接，放进 Web 请求里极易造成 stdio 协议污染与异步死锁，"
        "会让页面一直卡住。客户端脚本请继续在终端里演示。"
    )

    city = st.text_input(
        "查询城市（可选，留空则用脚本默认值「上海」）",
        key="mcp_city",
        placeholder="上海",
    )
    effective_timeout = min(int(timeout), MCP_TIMEOUT_CAP)
    st.caption(
        f"本模块超时上限 {MCP_TIMEOUT_CAP} 秒（实际使用 {effective_timeout} 秒）："
        "防止 MCP 服务端等不到 stdin 导致页面一直转圈。"
    )

    b1, b2, _spacer = st.columns([1, 1, 4])
    run_clicked = b1.button("▶ 开始探测", type="primary", key="mcp_run")
    if b2.button("🧹 清空输出", key="mcp_clear"):
        clear_results(KEY_MCP)

    if run_clicked:
        args = [city.strip()] if city.strip() else []
        with st.spinner("Agent 执行中..."):
            st.session_state[KEY_MCP] = run_python(
                SCRIPT_MCP_PROBE, args, effective_timeout, python_bin
            )

    render_result_if_any(KEY_MCP)


# ===========================================================================
# 8) 侧边栏 + 主流程
# ===========================================================================
def sidebar() -> tuple[str, Path, int]:
    st.sidebar.title("🧭 统一控制台")
    st.sidebar.caption("RAG ／ 多智能体 ／ 多模型路由 ／ MCP 探针")

    module = st.sidebar.radio(
        "功能模块",
        (
            "① RAG 知识库问答",
            "② 多智能体协作演示",
            "③ 多模型路由",
            "④ MCP 协议探针",
        ),
        index=0,   # 默认进入模块一
    )

    st.sidebar.divider()

    # ---- 解释器选择 ----
    interpreters = detect_interpreters()
    labels = []
    for p in interpreters:
        try:
            rel = p.relative_to(BASE_DIR)
        except ValueError:
            rel = p
        ver = interpreter_version(str(p))
        labels.append(f"{rel}{f'（Python {ver}）' if ver else ''}")

    choice = st.sidebar.selectbox(
        "Python 解释器",
        options=list(range(len(interpreters))),
        format_func=lambda i: labels[i],
        index=0,
        help="默认优先 .venv-rag（langchain / langgraph / chromadb / pymongo 都在里面）",
    )
    python_bin = interpreters[choice]

    timeout = st.sidebar.slider(
        "超时时间（秒）",
        min_value=30, max_value=900, value=DEFAULT_TIMEOUT, step=30,
        help="首次建向量库建议调到 300~600；模块四固定不超过 30 秒",
    )

    st.sidebar.divider()

    with st.sidebar.expander("脚本与环境自检", expanded=False):
        for name in (SCRIPT_RAG, SCRIPT_AGENT, SCRIPT_ROUTER, SCRIPT_MCP_PROBE):
            exists = (BASE_DIR / name).is_file()
            st.write(f"{'✅' if exists else '❌'} `{name}`")
        st.caption(f"工作目录：`{BASE_DIR}`")
        st.caption("密钥只通过 `os.environ` 透传给子进程，控制台不回显任何 Key。")

    if st.sidebar.button("🧹 清空全部输出", key="clear_all"):
        clear_results(*ALL_RESULT_KEYS)

    return module, python_bin, int(timeout)


def main() -> None:
    module, python_bin, timeout = sidebar()

    st.title("Agent 统一控制台")
    st.caption(
        "Streamlit 前端 + subprocess 后端：页面只负责拼参数，逻辑仍在各个原脚本里，"
        "子进程统一以 UTF-8 抓取 stdout / stderr。"
    )

    if module.startswith("①"):
        module_rag(python_bin, timeout)
    elif module.startswith("②"):
        module_multi_agent(python_bin, timeout)
    elif module.startswith("③"):
        module_router(python_bin, timeout)
    else:
        module_mcp_probe(python_bin, timeout)


if __name__ == "__main__":
    main()
