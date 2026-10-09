# scripts/legacy —— 迁移前的工程文件归档（只读留档，不参与运行）

本目录保存重构（2026-10，Streamlit Cloud 部署改造）之前的原始工程配置，
便于对照与回滚。**它们不会被任何代码引用**，也不会被 Streamlit Cloud 使用。

| 归档文件 | 原位置 | 说明 |
|---|---|---|
| `Dockerfile.legacy` | `/Dockerfile` | 旧镜像定义：`CMD ["python", "router.py", ...]`，入口是 CLI 脚本而非 Web 控制台，路径按「所有 .py 在根目录」假设编写 |
| `dockerignore.legacy.txt` | `/.dockerignore` | 旧构建忽略规则（`COPY . .` 时代的上下文瘦身） |

重构后启用的替代文件：

- 根目录 `Dockerfile`：入口改为 `streamlit run streamlit_app.py`，识别 `src/`、`data/`、`.streamlit/` 新结构；
- 根目录 `.dockerignore`：同步排除 `.venv*`、`logs/*`、`.env`、`.streamlit/secrets.toml`，并明确保留 `data/`。

回滚方式：把对应文件复制回仓库根、删除或改名现有同名文件即可，无需改动任何 Python 代码。
