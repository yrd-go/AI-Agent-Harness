# DEPLOY.md —— Streamlit Cloud 部署与排错手册

本文件只讲「上云」这一条链路：部署步骤、云端与本地的差异、常见报错对照。
项目结构与本地运行方式见 [README.md](README.md)。

---

## 一、部署三步

### 1. 推仓库

```bash
git add .
git commit -m "refactor: 目录规范化 + 动态路径，适配 Streamlit Cloud"
git push
```

提交前确认这三件事：

- `data/knowledge_base.txt`、`data/chroma_db/`、`data/test.db` **已在版本库里**
  （`.gitignore` 中关于 `chroma_db/` 的忽略规则已被移除，云端因此无需冷启动重建）；
- `.env` 与 `.streamlit/secrets.toml` **没有被提交**；
- 根目录存在 `streamlit_app.py` 与 `requirements.txt`。

### 2. 创建应用

1. 打开 <https://share.streamlit.io> → **New app**；
2. Repository / Branch 选好之后，**Main file path 填 `streamlit_app.py`**；
3. Python 版本建议 3.12（与本地 `.venv-rag` 对齐，`pymongo>=4.9` / `chromadb` 都有 wheel）；
4. Deploy。

### 3. 配置 Secrets（云端没有 .env）

`Settings → Secrets` 里粘贴（TOML 语法，值换成真实 Key）：

```toml
ZHIPU_API_KEY = "sk-你的真实Key"

# 可选：模型与端点覆盖
# ZHIPU_CHAT_MODEL = "glm-4-flash"

# 云端 localhost:27017 不可用，模块三 / 模块五需要外部 MongoDB
MONGO_URI = "mongodb+srv://user:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGO_DB = "agent_db"
MONGO_COLLECTION = "students"
```

保存后点 **Reboot app**。`src/paths.py` 的 `load_env()` 会把 Secrets 写进 `os.environ`
（已存在的环境变量优先，不会被覆盖），脚本读取方式与本地完全一致。

---

## 二、云端与本地到底哪里不一样

| 维度 | 本地 Windows | Streamlit Cloud (Linux) | 项目里的应对 |
|---|---|---|---|
| 路径分隔符 / 盘符 | `C:\...` | `/mount/src/...` | 全部用 `pathlib` / `os.path.join`，无字面量绝对路径 |
| 项目根位置 | 本地工作副本 | `/mount/src/<repo>` | `src/paths.py` 向上寻找 `requirements.txt` / `.env` 动态定位 |
| 解释器 | `.venv-rag/Scripts/python.exe` | 平台托管的单一解释器 | `dashboard.py` 优先虚拟环境、找不到就用 `sys.executable` |
| 密钥来源 | 根目录 `.env` | Cloud Secrets | `load_env()` 先 `.env` 再 `st.secrets`，都只写 `os.environ` |
| MongoDB | 常跑在 `localhost:27017` | 没有 localhost 服务 | 用 Secrets 配 `MONGO_URI`，未配置时页面给出友好提示而非崩溃 |
| 文件系统 | 持久 | 每次重启是干净容器（可写但会丢） | 向量库随仓库提交；`logs/` 只当临时输出 |
| 控制台编码 | 可能是 GBK | UTF-8 | 子进程显式注入 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` |

---

## 三、上线后自检（按顺序）

1. **侧边栏 → 脚本与环境自检**：5 个模块应全部显示 ✅，并显示仓库根、解释器、数据目录、配置来源。
2. **模块②多智能体**：无外部依赖，点一下应当立刻成功——它是最干净的「环境是否健康」探针。
3. **模块③路由**：输入 `帮我查学生2`。若报 MongoDB 连接失败 → Secrets 里的 `MONGO_URI` 没配或不可达。
4. **模块①RAG**：先在侧边栏把超时时间调到 300~600 秒再提问。首次若向量库不可读会重建，较慢。
5. **模块⑤Function Calling**：退出码 1 表示「模型没有真正调用工具」（脚本既定语义），不等于崩溃；
   确认 `ZHIPU_API_KEY` 与 `MONGO_URI` 都正确后即可正常走到 `tool_calls`。
6. **模块④MCP 探针**：需要子进程 stdio 通信，Cloud 上允许；若报权限/管道错误，多半是平台限制，
   请改用普通终端运行 `python src/mcp_demo/mcp_protocol_probe.py`。

在云端终端（Manage app → Console）或本地仓库根都可以跑：

```bash
python scripts/health_check.py        # 全量自检：目录/硬编码路径/导入/路径常量/启动烟雾
python scripts/import_check.py        # 只查跨目录 import 与关键路径是否可达
```

---

## 四、常见报错对照表

| 现象 | 根因 | 处理 |
|---|---|---|
| `FileNotFoundError: .../data/knowledge_base.txt` | 数据文件没随仓库提交，或本地跑的是旧目录 | 确认 `data/knowledge_base.txt` 已提交；本地再跑一次 `scripts/health_check.py` |
| `ModuleNotFoundError: No module named 'ui'` / `'paths'` | 入口不是仓库根的 `streamlit_app.py`，或把入口填成了 `src/ui/dashboard.py` 却漏了路径引导 | Main file path 改回 `streamlit_app.py`；本文件顶部已内置 `sys.path` 注入 |
| `ModuleNotFoundError: No module named 'mcp'` | 项目里出现了名为 `mcp` 的目录并屏蔽了官方 SDK | 本仓库已把子包命名为 `src/mcp_demo/`，请勿改回 `mcp` |
| RAG 首次运行超时 | 向量库需重建 + 网络向量化耗时 | 侧边栏超时调到 300~600 秒；或把 `data/chroma_db/` 提交进仓库 |
| `ZHIPU_API_KEY: 未配置` | 云端没配 Secrets / 本地 `.env` 键名带 BOM | Secrets 里补 `ZHIPU_API_KEY`；`.env` 另存为 UTF-8 无 BOM |
| `MongoDB 操作出错：localhost:27017 ...` | 云端没有本地 Mongo | Secrets 配 Atlas 的 `MONGO_URI` |
| 中文显示为 `Ϊ` 之类乱码 | 子进程输出按 GBK 编码被 UTF-8 解码（旧版 Windows 现象） | 已由 `subprocess_env()` 统一注入 UTF-8，无需手动处理 |
| `StreamlitAPIException: set_page_config` 重复调用 | 页面模块被重复执行 | 用 `streamlit_app.py` 单入口启动，不要在 Cloud 上另配别的入口 |

---

## 五、自建容器（可选）

不想用 Cloud、要在自己服务器/内网跑时：

```bash
docker build -t my-agent-console .
docker run --rm -p 8501:8501 \
  -e ZHIPU_API_KEY="sk-xxxx" \
  -e MONGO_URI="mongodb://host.docker.internal:27017/" \
  my-agent-console
# 浏览器打开 http://localhost:8501
```

镜像内的结构与仓库一致（`WORKDIR /app` 即仓库根），路径解析逻辑完全相同；
密钥一律走 `-e` / `--env-file`，绝不写进镜像（`.dockerignore` 已排除 `.env` 与 `secrets.toml`）。
迁移前的旧 Dockerfile 归档在 `scripts/legacy/`。
