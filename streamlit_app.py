# -*- coding: utf-8 -*-
"""
streamlit_app.py —— Streamlit Cloud 入口（仓库根目录）
================================================================================

为什么入口放在仓库根目录、而不是直接指向 src/ui/dashboard.py：
    Streamlit Cloud 默认以仓库根的 ``streamlit_app.py`` 为入口；而本项目的
    页面脚本位于 ``src/ui/dashboard.py``，它需要用「仓库根」作为锚点去定位
    ``data/`` 等资源。这个文件只做三件事：

        1. 用 ``Path(__file__)`` 动态算出仓库根（云端是 Linux 路径）；
        2. 把仓库根与 ``src/`` 注入 sys.path，使 ``src/ui/dashboard.py``
           里的 ``from paths import ...`` 成立（不依赖运行时的当前工作目录）；
        3. 以 ``__main__`` 语义执行页面脚本。

    因此页面显式调用 project root 下的 streamlit_app.py 会正确执行且只执行一次，
    无需改动 dashboard.py 的内部结构。

本地运行：
    streamlit run streamlit_app.py
云端运行：
    Streamlit Cloud 会自动发现本文件（Main file path 也可手填 streamlit_app.py）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 动态定位仓库根：本文件就在根目录下，无需任何硬编码路径
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

for _path in (PROJECT_ROOT, SRC_DIR):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from paths import load_env  # noqa: E402  (必须先完成 sys.path 注入)

# 先加载配置（本地 .env / 云端 Secrets），并把结果留在 session_state 里供页面展示
load_env()

import streamlit as st  # noqa: E402

try:
    from ui import dashboard as _dashboard
except Exception as exc:  # noqa: BLE001  入口层兜底，避免云端只给一行红字
    st.error(
        "启动失败：无法加载页面模块 `src/ui/dashboard.py`。\n\n"
        f"错误类型：`{type(exc).__name__}`\n\n"
        f"错误信息：`{exc}`\n\n"
        "排查建议：\n"
        "1. 确认 `src/ui/dashboard.py` 存在且未被移动；\n"
        "2. 确认 `requirements.txt` 已安装（Streamlit Cloud 会自动安装）；\n"
        "3. 打开 Manage app → 日志，查看完整堆栈。"
    )
    st.stop()
else:
    _dashboard.main()
