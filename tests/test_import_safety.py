# -*- coding: utf-8 -*-
"""
tests/test_import_safety.py —— 「任何模块都不得在导入期退出进程」的回归测试

这条测试的由来（真实事故）：
    CI 第一次跑就红了：step「跨目录 import 与路径常量自检」失败，而单元测试全过。
    根因是 src/multi_agent_demo.py 在**模块顶层**写了 `sys.exit(1)`（用来提示没装
    langgraph）。SystemExit 继承 BaseException，`except Exception` 抓不到它，
    于是 scripts/import_check.py 自己被杀掉、返回非零退出码。
    这类问题只在「干净环境（没装第三方依赖）」里出现，本机装了依赖反而发现不了 ——
    所以必须用「进程内屏蔽第三方依赖」的办法把它固化成测试。

做法：
    把第三方依赖的根包在 sys.modules 里置为 None（等价于「没装」），逐个导入
    src/ 下的模块，断言没有模块在导入期调用 sys.exit / raise SystemExit。
    因缺依赖而抛 ImportError 是允许的（那是预期行为）。

    python -m unittest discover -s tests -v
    python tests/run_all.py            # 受限环境（不能用 python -m）时用这个
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC = PROJECT_ROOT / "src"

for _path in (str(PROJECT_ROOT), str(SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# 可能不存在的第三方根包：置为 None 后 `import` 会抛 ImportError
THIRD_PARTY_ROOTS = (
    "langgraph", "langchain", "langchain_core", "langchain_openai",
    "langchain_community", "langchain_text_splitters", "langchain_mcp_adapters",
    "chromadb", "pymongo", "streamlit", "dotenv", "mcp", "numpy", "openai",
)


def src_module_names() -> list[str]:
    """src/ 下所有可导入的模块名（相对 src/ 的点分路径，跳过 __init__）。"""
    names = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        names.append(".".join(path.relative_to(SRC).with_suffix("").parts))
    return names


class PoisonedDependencies:
    """上下文管理器：模拟「第三方依赖一个都没装」的干净环境，退出时完整还原。"""

    def __enter__(self):
        self._third_party_saved: dict = {}
        self._project_saved: dict = {}
        for name, mod in list(sys.modules.items()):
            path = getattr(mod, "__file__", None) or ""
            if str(SRC) in path:
                self._project_saved[name] = mod
        for root in THIRD_PARTY_ROOTS:
            for key in [k for k in list(sys.modules) if k == root or k.startswith(root + ".")]:
                self._third_party_saved[key] = sys.modules.pop(key)
            sys.modules[root] = None      # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info):
        # 1) 清掉毒化条目与本次导入的项目内模块
        for root in THIRD_PARTY_ROOTS:
            for key in [k for k in list(sys.modules) if k == root or k.startswith(root + ".")]:
                sys.modules.pop(key, None)
        for name, mod in list(sys.modules.items()):
            path = getattr(mod, "__file__", None) or ""
            if str(SRC) in path:
                sys.modules.pop(name, None)
        # 2) 还原真实模块对象
        sys.modules.update(self._project_saved)
        sys.modules.update(self._third_party_saved)
        return False


class TestNoExitAtImportTime(unittest.TestCase):
    def test_no_source_module_exits_the_process_on_import(self):
        offenders = []
        with PoisonedDependencies():
            for name in src_module_names():
                sys.modules.pop(name, None)
                try:
                    importlib.import_module(name)
                except SystemExit as exc:
                    # 就是要抓这个：模块顶层不该退出进程
                    offenders.append(f"{name}: 导入期 sys.exit({exc.code!r})")
                except Exception:
                    pass  # 缺依赖导致的 ImportError 等属预期
        self.assertEqual(
            offenders,
            [],
            "以下模块在导入期就退出了进程，会让 import 自检工具被带崩：\n  "
            + "\n  ".join(offenders),
        )

    def test_multi_agent_demo_defers_missing_langgraph_to_runtime(self):
        """缺 langgraph 时：模块要能导入成功，把错误推迟到真正建图时报。"""
        with PoisonedDependencies():
            sys.modules.pop("multi_agent_demo", None)
            mod = importlib.import_module("multi_agent_demo")
            self.assertIsNotNone(
                mod.LANGGRAPH_ERROR, "缺 langgraph 时应当记录错误，而不是在导入期退出"
            )
            with self.assertRaises(SystemExit):
                mod.build_graph()


class TestImportCheckIsResilient(unittest.TestCase):
    def test_describe_system_exit_mentions_code(self):
        scripts_dir = PROJECT_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import import_check  # noqa: PLC0415

        self.assertIn("sys.exit", import_check.describe_system_exit(SystemExit(1)))
        self.assertIn("'boom'", import_check.describe_system_exit(SystemExit("boom")))

    def test_import_check_catches_system_exit_before_exception(self):
        """源码级断言：SystemExit 必须单独接（它是 BaseException，不是 Exception）。"""
        text = (PROJECT_ROOT / "scripts" / "import_check.py").read_text(encoding="utf-8")
        self.assertIn("except SystemExit", text)
        # 只看「导入检查」那一段：SystemExit 分支必须写在 except Exception 之前，
        # 否则永远命不中（SystemExit 不是 Exception 的子类）。
        # 注意不能对全文做 index —— 文件开头还有无关的 `except Exception`。
        body = text[text.index("# 页面模块"):]
        self.assertIn("except SystemExit", body)
        self.assertLess(
            body.index("except SystemExit"),
            body.index("except Exception"),
            "SystemExit 分支必须紧邻在 except Exception 之前",
        )


if __name__ == "__main__":
    unittest.main()
