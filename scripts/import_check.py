# -*- coding: utf-8 -*-
"""
scripts/import_check.py —— 只导入、不执行页面（供 health_check.py 与人工排查使用）
==================================================================================

用途：验证「跨目录 import + 路径常量」在当前环境是否成立，而不触发任何网络请求、
不启动 Streamlit 服务。尤其适合排查云端部署时的 ImportError / ModuleNotFoundError。

    python scripts/import_check.py

退出码：
    0 = 没有发现真实问题（可能有个别模块因缺第三方依赖「跳过验证」）
    1 = 存在真实问题（本项目自有模块导入失败 / 关键路径缺失）

为什么要把「缺第三方依赖」和「代码坏了」分开（重要）：
    早期版本把两者都只 print、不记入 problems，于是 6 个核心模块全导入失败时
    仍然输出「路径与导入全部正常」并返回 0 —— 自检假绿比没有自检更危险。
    现在规则明确：
        缺第三方依赖（ModuleNotFoundError，且缺的不是本项目模块）-> 跳过验证并列出
        其他任何异常（语法错误 / 自有模块缺失 / 导入期抛错）      -> 计入 problems，返回 1

输出示例：
    PROJECT_ROOT     : /mount/src/AI-Agent-Harness
    src 在 sys.path  : True
    ui.dashboard     : 导入成功
    paths.KB_FILE    : /mount/src/AI-Agent-Harness/data/knowledge_base.txt（存在）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本项目自有的顶层模块：这些导入失败一定是真问题，绝不能当成「缺依赖」放过
PROJECT_MODULES = frozenset({
    "paths", "ui", "core", "mcp_demo", "rag_demo", "multi_agent_demo", "tests",
})


def classify(exc: Exception) -> tuple[str, str]:
    """把导入失败分成 skip / fail 两类，避免「缺依赖」掩盖「代码坏了」。

    返回 ("skip", 说明) 表示本次跳过验证；返回 ("fail", 说明) 表示真失败。
    """
    if isinstance(exc, ModuleNotFoundError):
        missing = getattr(exc, "name", "") or ""
        head = missing.split(".")[0]
        if head and head not in PROJECT_MODULES:
            return "skip", f"缺第三方依赖 `{missing}`（未安装，本次跳过验证）"
    return "fail", f"{type(exc).__name__}: {exc}"


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
    skipped: list[str] = []

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
        kind, why = classify(exc)
        if kind == "skip":
            print(f"[SKIP] ui.dashboard 未验证：{why}")
            skipped.append(f"ui.dashboard（{why}）")
        else:
            print(f"[FAIL] ui.dashboard 导入失败：{why}")
            problems.append(f"导入 ui.dashboard 失败：{why}")

    # 各子模块：缺第三方依赖 -> 跳过验证并列出；其他异常 -> 真失败
    for module in ("core.router", "core.query_student", "core.init_db",
                   "core.agent_tool_demo", "rag_demo", "multi_agent_demo"):
        try:
            __import__(module)
            print(f"{module:<18}: 导入成功")
        except Exception as exc:  # noqa: BLE001
            kind, why = classify(exc)
            if kind == "skip":
                print(f"{module:<18}: 跳过（{why}）")
                skipped.append(f"{module}（{why}）")
            else:
                print(f"{module:<18}: 导入失败 -> {why}")
                problems.append(f"导入 {module} 失败：{why}")

    if problems:
        print("\n结论：存在问题")
        for item in problems:
            print(f"  - {item}")
        return 1

    if skipped:
        print(f"\n结论：路径与导入正常（{len(skipped)} 个模块因缺第三方依赖跳过，未验证）")
        for item in skipped:
            print(f"  - {item}")
        return 0

    print("\n结论：路径与导入全部正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
