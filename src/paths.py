# -*- coding: utf-8 -*-
"""
src/paths.py —— 全项目唯一的路径与环境变量中心（云端 Linux / 本地 Windows 通用）
=================================================================================

为什么要这个文件：
    重构后脚本分布在 src/、src/core/、src/mcp/、src/ui/ 等不同深度。
    如果每个脚本各自写 ``Path(__file__).parent.parent``，一旦以后有人再挪动
    文件，路径就会静默指错目录（典型症状：云端报 FileNotFoundError）。
    所以这里集中做一次「动态向上寻找项目根目录」，所有脚本只 import 常量。

动态定位规则（find_project_root）：
    从本文件所在目录开始逐级向上，第一个包含 .env 或 requirements.txt 的目录
    就是项目根目录（PROJECT_ROOT）。找不到时回退到本文件的上两级目录。
    这意味着所有资源都用绝对路径拼装，与「运行时的工作目录」彻底解耦。

云端注意：
    Streamlit Cloud 上不存在 .env（密钥用 Secrets），此时 markers 里的
    requirements.txt 就是根目录锚点，因此定位依然成立。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "PROJECT_ROOT", "SRC_DIR", "ASSETS_DIR", "DATA_DIR", "LOGS_DIR", "SCRIPTS_DIR",
    "KB_FILE", "CHROMA_DIR", "TEST_DB", "ENV_FILE", "SECRETS_FILE", "SERVER_SCRIPT",
    "INTERPRETER", "VENV_CANDIDATES",
    "find_project_root", "load_env", "subprocess_env",
]

# 根目录锚点文件：命中任意一个即认为是项目根目录
_ROOT_MARKERS = ("requirements.txt", ".env")

# 虚拟环境里的解释器（本地优先用装了 langchain/langgraph/chromadb 的那个环境）。
# 云端没有这些目录，list 为空，自动退化为当前解释器 INTERPRETER。
_VENV_RELATIVE_PYTHONS = (
    ".venv-rag/Scripts/python.exe",   # Windows + .venv-rag
    ".venv/Scripts/python.exe",       # Windows + .venv
    ".venv-rag/bin/python",           # Linux/macOS + .venv-rag
    ".venv/bin/python",               # Linux/macOS + .venv
)


def find_project_root(start: Path | None = None) -> Path:
    """从 start（默认本文件所在目录）向上逐级查找项目根目录。"""
    current = (start or Path(__file__).resolve().parent).resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).is_file() for marker in _ROOT_MARKERS):
            return candidate
    # 兜底：本文件位于 <root>/src/paths.py，所以上两级就是根目录
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT: Path = find_project_root()
SRC_DIR: Path = PROJECT_ROOT / "src"
ASSETS_DIR: Path = PROJECT_ROOT / "assets"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"

# ---- 数据资源（重构后统一收纳在 data/ 下）----
KB_FILE: Path = DATA_DIR / "knowledge_base.txt"
CHROMA_DIR: Path = DATA_DIR / "chroma_db"
TEST_DB: Path = DATA_DIR / "test.db"

# ---- 脚本之间的互相调用（子进程用绝对路径启动，与工作目录无关）----
SERVER_SCRIPT: Path = SRC_DIR / "mcp_demo" / "mcp_weather_server.py"
PROBE_SCRIPT: Path = SRC_DIR / "mcp_demo" / "mcp_protocol_probe.py"
RAG_SCRIPT: Path = SRC_DIR / "rag_demo.py"
MULTI_AGENT_SCRIPT: Path = SRC_DIR / "multi_agent_demo.py"
ROUTER_SCRIPT: Path = SRC_DIR / "core" / "router.py"
QUERY_STUDENT_SCRIPT: Path = SRC_DIR / "core" / "query_student.py"
AGENT_TOOL_SCRIPT: Path = SRC_DIR / "core" / "agent_tool_demo.py"

# ---- 配置 ----
ENV_FILE: Path = PROJECT_ROOT / ".env"
SECRETS_FILE: Path = PROJECT_ROOT / ".streamlit" / "secrets.toml"

# ---- 解释器 ----
INTERPRETER: Path = Path(sys.executable)
VENV_CANDIDATES: tuple[Path, ...] = tuple(
    PROJECT_ROOT / rel for rel in _VENV_RELATIVE_PYTHONS
)


def bootstrap() -> Path:
    """把仓库根与 src/ 加入 sys.path，返回 PROJECT_ROOT。

    每个「可独立运行的脚本」在 import 本项目模块之前先调用一次即可：
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from paths import PROJECT_ROOT, bootstrap
        bootstrap()
    这样 ``import paths`` 与 ``import core.router`` 这类跨目录导入在任何
    工作目录、任何操作系统下都成立。
    """
    for path in (PROJECT_ROOT, SRC_DIR):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return PROJECT_ROOT


def _iter_declared_keys() -> list[str]:
    """列出 .env / .env.example / Secrets 里出现过的键名。

    只返回「键名」，绝不返回键值，避免密钥进入日志或页面。
    """
    keys: list[str] = []
    for file in (ENV_FILE, PROJECT_ROOT / ".env.example"):
        try:
            for raw in file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key and key not in keys:
                    keys.append(key)
        except OSError:
            continue
    try:  # Streamlit Secrets 的顶层键（云端）
        import streamlit as st

        keys.extend(k for k in getattr(st, "secrets", {}) if k not in keys)
    except Exception:
        pass
    return keys


def load_env() -> dict:
    """加载配置：先读根目录 .env，再用 Streamlit Secrets 补齐缺项。

    返回值只有「是否加载到 / 来源描述 / 键数量」，不含任何键值：
        {"env_file": str|None, "secrets_used": bool, "keys": int, "source": str}
    设计原则：只写入 os.environ（子进程可通过 os.environ 透传），
    绝不打印、绝不回显、绝不返回任何 Key 的内容。
    """
    loaded: list[str] = []
    env_file_used: str | None = None

    # ---- 1) 本地 .env（云端通常不存在，失败也不影响）----
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    if load_dotenv is not None and ENV_FILE.is_file():
        try:
            load_dotenv(str(ENV_FILE), override=False)
            env_file_used = str(ENV_FILE)
            loaded.append(".env")
        except Exception:
            env_file_used = None

    # ---- 2) Streamlit Secrets（云端推荐方式）----
    secrets_used = False
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets:
            for key in list(secrets):
                if not os.environ.get(key):          # 不覆盖已存在的环境变量
                    os.environ[key] = str(secrets[key])
                    secrets_used = True
            if secrets_used:
                loaded.append("st.secrets")
    except Exception:
        # 没装 streamlit / 无 secrets.toml / 非 Streamlit 运行环境：都属正常
        pass

    declared = _iter_declared_keys()
    configured = [k for k in declared if os.environ.get(k)]
    source = " + ".join(loaded) if loaded else "系统环境变量"
    return {
        "env_file": env_file_used,
        "secrets_used": secrets_used,
        "keys": len(configured),
        "source": source,
    }


def subprocess_env() -> dict:
    """构造子进程环境变量：透传配置 + 强制 UTF-8 + 允许子进程 import 本项目模块。

    云端 Linux 默认就是 UTF-8，显式设置无害；它主要解决 Windows 下
    管道输出按 GBK 编码导致的乱码问题。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    src_text = str(SRC_DIR)
    existing = env.get("PYTHONPATH", "")
    if src_text not in existing.split(os.pathsep):
        env["PYTHONPATH"] = f"{src_text}{os.pathsep}{existing}" if existing else src_text
    return env
