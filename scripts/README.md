# scripts —— 运维脚本、示例代码与归档

本目录不参与 Streamlit 应用的运行，只服务于「自检 / 演示 / 留档」。

| 路径 | 用途 |
|---|---|
| `health_check.py` | 重构后全量自检：目录结构、硬编码路径扫描、静态导入、路径常量、启动烟雾测试 |
| `import_check.py` | 只导入不执行：验证跨目录 `import` 与关键路径是否可达（排 `ModuleNotFoundError` 首选） |
| `js/` | Node.js 演示脚本（8 个，原在仓库根目录） |
| `legacy/` | 迁移前的 `Dockerfile` / `.dockerignore` 归档 |

## 常用命令（在仓库根执行）

```bash
python scripts/health_check.py            # 全量检查（含真实拉起各脚本的子进程）
python scripts/health_check.py --quick    # 跳过子进程烟雾测试，秒出结果
python scripts/import_check.py            # 跨目录 import 与路径可达性
```

`health_check.py` 的退出码：`0` = 无失败项；`1` = 存在失败项（输出里会列出文件与行号）。

> 在受限沙箱（例如 DSH 的 workspace-write 模式）里运行时，涉及**子进程管道**的两个 MCP 用例
> 会因环境禁止创建管道而显示 `[SKIP]`，这属于环境限制而非代码问题；
> 请在普通终端复跑 `python src/mcp_demo/mcp_protocol_probe.py` 完成验证。

## js/ 说明

这些脚本是早期 Node.js 练习（HTTP 服务、SQLite 增删查、排序/斐波那契、GitHub Issues 抓取等），
与 Streamlit 应用无依赖关系，仅作学习留档。示例：

```bash
node scripts/js/employee_api.js          # 启动一个本地 HTTP 服务
node scripts/js/query_student.js         # 查询示例 SQLite（data/test.db）
```

注意：这些 JS 脚本里的 SQLite 路径是脚本自身相对路径，若把 `data/test.db` 挪走需同步修改，
它们不属于本次「Python 路径动态化」的改造范围。
