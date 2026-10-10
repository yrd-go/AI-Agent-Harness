# DEPLOY_STRUCTURE.md —— 目录重构与部署说明（Streamlit Cloud）

> 本文件记录 2026-10 的目录重构：Python 代码进 `src/`，数据进 `data/`，
> JS 与运维脚本进 `scripts/`，所有路径改为**基于脚本自身位置动态计算**的绝对路径。
> 项目介绍、架构与实测数据见根目录的 [README.md](README.md)（**已同步为重构后的命令**）；
> 19 段踩坑与排错复盘见 [docs/PITFALLS.md](docs/PITFALLS.md)（44 张截图已归入 `docs/images/`）；
> 云端部署的详细排错清单（报错对照表）见 [DEPLOY.md](DEPLOY.md)。

---

## 一、为什么重构（一句话）

旧结构把所有 `.py` 摊在仓库根目录，且脚本之间用「与本文件同级」推断路径——
一旦移动文件或部署到云端 Linux，路径就会静默指错。
重构后由 `src/paths.py` **统一动态定位仓库根**，本地 Windows 与云端 Linux 行为一致。

## 二、新目录结构

```
my-agent/
├─ streamlit_app.py            # ★ 部署入口（Streamlit Cloud 的 Main file path 填它）
├─ requirements.txt            # 依赖清单（云端自动安装）
├─ README.md                   # ★ 项目定位 / 架构 / 快速开始 / 实测数据 / 已知限制
├─ LICENSE                     # MIT
├─ DEPLOY_STRUCTURE.md         # 本文件
├─ Dockerfile / .dockerignore  # 自建容器部署（可选路径）
├─ .env / .env.example         # 本地密钥（.env 不提交）与模板
├─ .streamlit/
│  ├─ config.toml              # 主题 / server 配置
│  └─ secrets.toml.example     # 云端 Secrets 模板
├─ .github/workflows/ci.yml    # CI：单元测试 + 跨目录导入自检
├─ src/
│  ├─ paths.py                 # ★ 全项目唯一的路径 / 环境变量中心（含 mask_uri / mask_secrets）
│  ├─ rag_demo.py              # ① RAG 知识库问答
│  ├─ multi_agent_demo.py      # ② 多智能体协作（LangGraph 状态图）
│  ├─ core/                    # ③ 路由、⑤ Function Calling、MongoDB 工具
│  │  ├─ router.py  ├─ query_student.py  ├─ init_db.py
│  │  ├─ agent_tool_demo.py     └─ employee_api.py
│  ├─ mcp_demo/                # ④ MCP 服务端 / 客户端 / 旁路探针
│  │  ├─ mcp_weather_server.py  ├─ mcp_weather_client.py
│  │  └─ mcp_protocol_probe.py
│  └─ ui/dashboard.py          # Streamlit 页面实现（页面逻辑在这里）
├─ data/                       # 运行时数据（随仓库提交）
│  ├─ knowledge_base.txt       # RAG 知识库原文
│  ├─ chroma_db/               # 向量库（当前为 zhipu 2048 维）
│  └─ test.db                  # 示例 SQLite（Node.js 侧脚本使用）
├─ docs/
│  ├─ PITFALLS.md              # ★ 19 段踩坑与排错复盘
│  └─ images/                  # ★ 44 张实测截图（01~44，编号与正文对应）
├─ tests/                      # 纯标准库单元测试（52 用例）+ fixtures
│  ├─ run_all.py               # 不能用 python -m 的受限环境的测试入口
│  └─ fixtures/                # find_project_root 的静态 marker 目录（零运行时写盘）
├─ scripts/
│  ├─ health_check.py          # ★ 全量健康自检（三态结论：OK / WARN / FAIL）
│  ├─ import_check.py          # 跨目录 import / 路径排错
│  ├─ publish_docs_to_github.ps1  # 把本地文档与改动一键同步到 GitHub
│  ├─ js/                      # Node.js 演示脚本（8 个）
│  └─ legacy/                  # 迁移前的 Dockerfile 等归档
├─ logs/                       # 日志与临时输出
├─ assets/samples/             # 示例文本
└─ README_EN.md                # 英文说明：**只在远端维护**，本轮尚未同步（见 README 已知限制）
```

## 三、命令对照表（旧 → 新）

`README.md` 已经更新为重构后的命令；下表保留「旧 → 新」对照，方便对照历史截图与旧笔记
（功能完全一致）：

| 旧命令（README 里写的） | 新命令 |
|---|---|
| `python rag_demo.py "问题"` | `python src/rag_demo.py "问题"` |
| `python rag_demo.py --rebuild` | `python src/rag_demo.py --rebuild` |
| `python multi_agent_demo.py` | `python src/multi_agent_demo.py` |
| `python router.py "帮我查学生2"` | `python src/core/router.py "帮我查学生2"` |
| `python query_student.py 2` | `python src/core/query_student.py 2` |
| `python init_db.py` | `python src/core/init_db.py` |
| `python agent_tool_demo.py "问题"` | `python src/core/agent_tool_demo.py "问题"` |
| `python mcp_protocol_probe.py` | `python src/mcp_demo/mcp_protocol_probe.py` |
| `python mcp_weather_client.py` | `python src/mcp_demo/mcp_weather_client.py` |
| `python mcp_weather_server.py` | `python src/mcp_demo/mcp_weather_server.py` |
| `node init_db.js` / `node query_student.js 2` | `node scripts/js/init_db.js` / `node scripts/js/query_student.js 2` |
| `streamlit run web_demo/dashboard.py` | `streamlit run streamlit_app.py` |
| `docker run ... my-agent-debugger`（CLI 入口） | `docker run -p 8501:8501 ... my-agent-console`（Web 入口） |

> 这些脚本都从**仓库根**启动即可，不需要设置 `PYTHONPATH`：每个脚本会自动算出仓库根与 `src/` 并注入 `sys.path`。

## 四、本地运行

```powershell
# 依赖（建议用项目自带虚拟环境）
.\.venv-rag\Scripts\python.exe -m pip install -r requirements.txt

# 自检：目录 / 硬编码路径 / 导入 / Path 边界 / 路径常量 / 启动烟雾
.\.venv-rag\Scripts\python.exe scripts\health_check.py

# 启动控制台（本地与云端同一个入口文件）
.\.venv-rag\Scripts\python.exe -m streamlit run streamlit_app.py
# 浏览器打开 http://localhost:8501
```

## 五、部署到 Streamlit Cloud

1. 仓库推送到 GitHub 后，打开 <https://share.streamlit.io> → **New app**；
2. **Main file path 必须填 `streamlit_app.py`**
   ⚠️ 不要再填旧的根目录 `dashboard.py`——那是重构前的遗留文件，它的脚本路径写的是「根目录下」，
   云端会报 `找不到脚本文件：/mount/src/rag_demo.py`；
3. Python 版本建议 3.12；
4. `Settings → Secrets` 粘贴 `.streamlit/secrets.toml.example` 的内容并填真实值（云端**没有** `.env`）：

   ```toml
   ZHIPU_API_KEY = "sk-你的真实Key"
   # 可选：云端 localhost 不可用，模块③/⑤需要外部 MongoDB
   # MONGO_URI = "mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
   ```

5. 保存后 **Reboot app**。

## 六、云端与本地差异（本项目的应对）

| 维度 | 本地 Windows | Streamlit Cloud (Linux) | 应对 |
|---|---|---|---|
| 路径 | `C:\...` | `/mount/src/...` | `src/paths.py` 动态定位，无字面量绝对路径 |
| 解释器 | `.venv-rag/Scripts/python.exe` | `/home/adminuser/venv/bin/python` | 页面优先虚拟环境，找不到就用 `sys.executable` |
| 密钥 | 根目录 `.env` | Cloud Secrets | `load_env()` 先 `.env` 再 `st.secrets`，只写 `os.environ` |
| MongoDB | 本地 27017（可选，不装也能跑） | 无 localhost 服务 | 默认 `[mock]` 兜底；要用真实数据请用 **MongoDB Atlas** + 配置 `MONGO_URI`（见第八节） |
| 文件系统 | 持久 | 每次重启是干净容器 | 向量库随仓库提交（`data/chroma_db/`） |

## 七、两个易踩的坑（本项目已内建防护）

### 1. 向量库维度必须与 Embedder 一致

`chroma_db` 的元数据里记录了 `embedder`，切换引擎必须重建，否则报
`Collection expecting embedding with dimension of 2048, got 768`：

```powershell
# 当前仓库里的向量库是 zhipu（2048 维，181 片段）——云端默认路径直接可用
python src/rag_demo.py --embedder zhipu --rebuild     # 切到云端智谱（需要 API Key）
python src/rag_demo.py --embedder ollama --rebuild    # 切到本地 Ollama（需先 ollama serve + pull nomic-embed-text）
```

### 2. `persist_directory` 必须传字符串

langchain 会把该值原样交给 chromadb，而 `chromadb/db/impl/sqlite.py` 内部执行
`persist_directory + "/chroma.sqlite3"`；传 `Path` 对象会报
`TypeError: unsupported operand type(s) for +: 'WindowsPath' and 'str'`（新版 chromadb 则是 pydantic 校验错误）。
因此 `src/rag_demo.py` 在边界处统一用 `os.fspath(...)`；
`scripts/health_check.py` 的【3.5/5】会自动扫描这类写法，防止回归。

## 八、MongoDB 兜底开关 `STUDENT_ALLOW_MOCK`

本地与云端都没有 `localhost:27017` 的 MongoDB 时，模块③「查学生」与模块⑤「Function Calling」：

| 开关 | 行为 |
|---|---|
| 不设置（默认 `true`） | 返回 `status=mock` 的**模拟数据**并在输出里标注 `[mock]`，链路继续跑完 |
| `STUDENT_ALLOW_MOCK=false` | 严格模式：连不上直接报错（退出码 3），不再静默降级 |

> **这是刻意设计的降级行为，不是缺陷。** 无数据库环境下页面依然能完整演示「路由 → 工具调用 → ReAct 闭环」，
> 同时通过 `status=mock` 与 `[mock]` 标注把"这不是真实数据"讲清楚，避免误判。
> 本地与云端默认都保持这个模式；需要真实数据时再按下一节接 Atlas。

配好真实的 MongoDB（如 Atlas）后建议切到严格模式，避免把 mock 误当真实数据。

### 需要连接真实 MongoDB 时：请使用 MongoDB Atlas

> **如果需要连接真实 MongoDB，请使用 MongoDB Atlas，并配置 `MONGO_URI`。**

本地自建 `mongod` 仅对本地调试有意义（云端容器里没有 localhost 服务，帮不到部署）；
要让**云端**也用上真实学生数据，请走 Atlas：

1. 注册 <https://www.mongodb.com/cloud/atlas> → 创建 **M0 免费层**集群（永久免费，512 MB 足够本项目）；
2. 在 `Database Access` 建一个数据库用户，`Network Access` 里放行 `0.0.0.0/0`（Streamlit Cloud 出口 IP 不固定）；
3. 复制连接串，在**云端** `Settings → Secrets` 里加一行（键名必须是 `MONGO_URI`）：

   ```toml
   MONGO_URI = "mongodb+srv://<用户>:<密码>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
   MONGO_DB = "agent_db"
   MONGO_COLLECTION = "students"
   ```

4. **本地**想用同一份数据：把同样的键写进根目录 `.env`（`.env` 已被 `.gitignore` 忽略，不会提交）；
5. 首次使用先灌入 3 条示例数据（`init_db.py` 会创建 `agent_db.students`）：

   ```powershell
   python src/core/init_db.py
   # 验证真实数据已生效（不再出现 [mock]）
   python src/core/query_student.py 2
   ```

6. 确认稳定后，可在 Secrets / `.env` 里加 `STUDENT_ALLOW_MOCK = "false"` 切到严格模式，
   这样一旦 `MONGO_URI` 失效会立刻报错，而不会静默返回模拟数据。

## 九、安全约定

- `.env` 与 `.streamlit/secrets.toml` 已被 `.gitignore` 忽略，**绝不提交**；
- 代码只通过 `os.environ` 读取密钥，从不打印、不回显、不写日志；
- `scripts/health_check.py` 只报告「配置来源 + 识别到的键数量」，不读值；
- 若仓库里出现看起来像真实 Key 的字符串，请立即轮换。
