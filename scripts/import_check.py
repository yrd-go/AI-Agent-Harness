# -*- coding: utf-8 -*-
"""
scripts/import_check.py —— 只导入、不执行页面（供 health_check.py 与人工排查使用）
==================================================================================

用途：验证「跨目录 import + 路径常量」在当前环境是否成立，而不触发任何网络请求、
不启动 Streamlit 服务。尤其适合排查云端部署时的 ImportError / ModuleNotFoundError。

    python scripts/import_check.py

输出示例：
    PROJECT_ROOT     : /mount/src/my-agent
    src 在 sys.path  : True
    ui.dashboard     : 导入成功
    paths.KB_FILE    : /mount/src/my-agent/data/knowledge_base.txt（存在）
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    project_root = Path(__file__).resolve().parents[1]
    src_dir = project_root / "src"
    for path in (str(project_root), str(src_dir)):
        if path not in sys.path:
            sys.path.insert(0, path)

    problems: list[str] = []

    try:
        import paths  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 无法导入 src/paths.py：{type(exc).__name__}: {exc}")
        return 1

    print(f"PROJECT_ROOT     : {paths.PROJECT_ROOT}")
    print(f"src 在 sys.path  : {str(paths.SRC_DIR) in sys.path}")

    checks = {
        "knowledge_base.txt": paths.KB_FILE,
        "chroma_db 目录": paths.CHROMA_DIR,
        "MCP 服务端脚本": paths.SERVER_SCRIPT,
        "RAG 脚本": paths.RAG_SCRIPT,
        "路由脚本": paths.ROUTER_SCRIPT,
    }
    for name, path in checks.items():
        state = "存在" if path.exists() else "缺失"
        print(f"{name:<18}: {path}（{state}）")
        if not path.exists():
            problems.append(f"{name} 不存在：{path}")

    # 页面模块：只导入，不执行 main()
    try:
        import ui.dashboard as dashboard  # noqa: PLC0415

        print(f"ui.dashboard     : 导入成功（脚本目录 {dashboard.SCRIPT_RAG.parent}）")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"导入 ui.dashboard 失败：{type(exc).__name__}: {exc}")
        print(f"[FAIL] ui.dashboard 导入失败：{type(exc).__name__}: {exc}")

    # 各子模块（按依赖分组，缺第三方包时只提示不判失败）
    for module in ("core.router", "core.query_student", "core.init_db",
                   "core.agent_tool_demo", "rag_demo", "multi_agent_demo"):
        try:
            __import__(module)
            print(f"{module:<18}: 导入成功")
        except Exception as exc:  # noqa: BLE001
            print(f"{module:<18}: 导入失败（{type(exc).__name__}: {exc}）")

    if problems:
        print("\n结论：存在问题")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("\n结论：路径与导入全部正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
