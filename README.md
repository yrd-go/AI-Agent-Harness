# AI-Agent-Harness

**可运行的高可用 RAG + MCP Agent 底座**（含 44 组实测截图与排错复盘）

[![CI](https://github.com/yrd-go/AI-Agent-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yrd-go/AI-Agent-Harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-green)

一键体验（Streamlit 公网 Demo）：<https://ai-agent-harness-edjmumadkd9e3lqsmtf3ff.streamlit.app>

> 公网 Demo 没有本机 Ollama 与 MongoDB，模块 ③/⑤ 会走**明确的 mock 标注**而不是真实数据；
> 降级链路的真实效果请按下方「实测数据」在本地复现。

---

## 目录

- [这个项目是什么 / 不是什么](#这个项目是什么--不是什么)
- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [五个模块](#五个模块)
- [实测数据（含测量口径）](#实测数据含测量口径)
- [三个核心工程问题的处置](#三个核心工程问题的处置)
- [测试与自检](#测试与自检)
- [已知限制](#已知限制)
- [部署](#部署)
- [目录结构](#目录结构)
- [安全约定](#安全约定)
- [踩坑复盘（19 段）](docs/PITFALLS.md)
- [后续规划](#后续规划)

---

## 这个项目是什么 / 不是什么

**是什么**：一个把「大模型应用最容易在生产里翻车的三个坑」逐个收敛成可复现、可验证处置的工程底座 ——
**模型不可用**（生成阶段主备降级 + 快速失败）、**向量空间错配**（元数据一致性守卫 + 一条命令重建）、
**协议线污染**（stdout/stderr 纪律 + 可复现故障的旁路探针）。附带一个把五个模块串起来的 Streamlit 控制台。

**不是什么**：不是模型训练/微调项目，不是高并发生产系统。
本仓库如实标注了[已知限制](#已知限制)——包括**检索侧尚未降级**、**无熔断/退避**、**无 RAG 量化评测**。
这些是下一步计划，而不是已经完成的能力。

技术栈：Python 3.10+ · LangChain / LangGraph · Chroma · MCP（stdio）· 智谱 GLM-4-Flash · 本地 Ollama · Streamlit · Docker

---

## 快速开始

```bash
git clone https://github.com/yrd-go/AI-Agent-Harness.git
cd AI-Agent-Harness

# 1) 依赖（建议 3.11/3.12；3.14 下 chromadb 可能没有 wheel）
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) 配置（.env 不会进版本库；也可先用 Streamlit Secrets）
cp .env.example .env                # Windows: copy .env.example .env
#    最少填一行：ZHIPU_API_KEY=sk-xxxx
#    需要真实学生数据时再填 MONGO_URI（本地 mongod 或 MongoDB Atlas）

# 3) 启动控制台（本地与云端同一个入口）
streamlit run streamlit_app.py
#    浏览器打开 http://localhost:8501
```

**只想跑命令行**（不需要 Streamlit）：

```bash
python src/rag_demo.py "我的VPN坏了"                   # ① RAG：改写 + 混合检索 + 双引擎生成
python src/rag_demo.py "我的VPN坏了" --no-rerank        #    对照组：纯向量检索
python src/rag_demo.py --rebuild                       #    重建向量库（切换 Embedder 必须重建）
python src/multi_agent_demo.py                         # ② 多智能体：Agent Loop + 防死循环
python src/core/router.py "帮我查学生2"                  # ③ 路由：本地脚本 / 免费翻译 / DeepSeek
python src/mcp_demo/mcp_protocol_probe.py              # ④ MCP 探针：三步协议验证
python src/mcp_demo/mcp_protocol_probe.py --break-stdout   #    ★ 负向复现：stdout 污染协议线
python src/core/agent_tool_demo.py                     # ⑤ Function Calling：ReAct 闭环
```

> `.venv-rag/` 是作者本机使用的环境名，脚本会自动探测（`.venv` / `.venv-rag` 都认），
> 找不到就用当前解释器。入口一律从**仓库根**执行，不需要手动设 `PYTHONPATH`。

---

## 系统架构

### ① RAG 主链路：检索与生成解耦 + 降级 + 向量库一致性守卫

```mermaid
graph TD
    Q[用户提问] --> RW{查询改写<br/>glm-4-flash}
    RW -->|成功| HQ[改写检索词 + 关键词]
    RW -->|失败/无 Key| OQ[沿用原始问题 + 本地分词]

    HQ --> VS[(Chroma 向量库)]
    OQ --> VS
    VS -->|embedder 元数据不一致| GUARD[拒绝检索<br/>给出 --rebuild 命令]
    VS -->|Top-K 片段| FUSE[混合打分<br/>0.7×向量 + 0.3×关键词]

    FUSE --> GEN[生成引擎]
    GEN -->|主引擎| ZP[智谱 GLM-4-Flash]
    ZP -->|超时/限流/鉴权失败| FB{自动降级}
    FB -->|auto 模式| OL[本地 Ollama Qwen2.5-3B]
    FB -->|--engine zhipu / --no-fallback| FF[快速失败<br/>退出码 2]
    ZP -->|成功| ANS[最终回答]
    OL -->|兜底| ANS
```

### ② MCP 跨进程工具调用 + 旁路探针（含负向复现）

```mermaid
graph LR
    LC[LangChain 客户端] -->|MCPAdapter| SRV
    PR[旁路探针<br/>mcp_protocol_probe.py] -->|initialize / tools-list / tools-call| SRV
    PR -.->|--break-stdout<br/>MCP_POLLUTE_STDOUT=1| SRV
    SRV[MCP Server 子进程<br/>stdio 传输] --> TOOL[get_current_weather]
    SRV -->|stdout = 协议线| LC
    SRV -->|logging → stderr| LOG[日志<br/>不污染协议线]
    PR -->|协议层失败| DIAG[结构化诊断 + 退出码 4]
```

### ③ 多智能体 Agent Loop（LangGraph 状态图）

```mermaid
graph TD
    START --> R[Retriever 检索 Agent]
    R --> V[Reviewer 审查 Agent]
    V -->|条件边: retry<br/>最多 2 次| R
    V -->|approved| END1[结束]
    V -->|give_up<br/>防死循环| END2[安全退出]
```

### ④ 多模型路由（按关键词把任务送到不同成本档）

```mermaid
graph LR
    I[自然语言指令] --> M{关键词匹配<br/>顺序即优先级}
    M -->|查 + 学生| A[本地查询脚本<br/>零成本]
    M -->|翻译| B[MyMemory 免费接口<br/>零成本]
    M -->|代码| C[DeepSeek 大模型<br/>有成本]
    M -->|未命中| D[打印用法<br/>退出码 1]
```

---

## 五个模块

| # | 模块 | 命令 / 入口 | 需要什么 | 是否需要 API Key |
|---|---|---|---|---|
| ① | RAG 知识库问答（改写 + 混合检索 + 降级） | `src/rag_demo.py` | 向量库 `data/chroma_db/`（随仓库提交） | 是（智谱）/ 可全离线（Ollama） |
| ② | 多智能体协作 + 防死循环 | `src/multi_agent_demo.py` | 仅 `langgraph` | 否（本地确定性演示） |
| ③ | 多模型路由 | `src/core/router.py` | 无 | 仅代码生成路由需要 DeepSeek |
| ④ | MCP 协议探针（可负向复现） | `src/mcp_demo/mcp_protocol_probe.py` | `mcp>=2` | 否 |
| ⑤ | Function Calling（ReAct + 工具封装） | `src/core/agent_tool_demo.py` | MongoDB（可选，缺省走 mock） | 是（智谱） |

统一 Web 控制台：五个模块都能在页面上点按运行，支持动态调超时/引擎/检索参数，输出统一 UTF-8 捕获。

---

## 实测数据（含测量口径）

**测量环境**：Windows 本机 · 16GB 内存 · **纯 CPU 推理**（无 GPU）· 本地模型 `qwen2.5:3b` + `nomic-embed-text` · 云端模型 `glm-4-flash` / `embedding-3`
**口径说明**：以下为**单次运行实测值**（截图见 [docs/PITFALLS.md](docs/PITFALLS.md)），
**不是多次平均，也没有做统计显著性检验**；网络与服务端负载会让同一条链路耗时明显波动。

| 场景 | 命令 | 实测耗时 | 备注 |
|---|---|---|---|
| 智谱生成回答 | `python src/rag_demo.py "..."` | 20.1 s | 主引擎正常路径 |
| 自动降级到本地 Ollama | 智谱超时后自动切换 | 71.1 s / 72 s | 两次不同场景实测；保住可用性，代价是慢 |
| 全离线链路（本地检索 + 本地生成） | `--engine ollama --embedder ollama` | 47.8 s | 全程不出网 |
| 本地向量库重建 | `--embedder ollama --rebuild` | 73.8 s（181 片段）/ 6.2 s（362 片段，智谱） | 与 Embedder 和片段数强相关 |
| 本地向量检索 | 提问后的 Top-K 召回 | 0.06 s | 检索阶段本身很快，瓶颈在生成 |
| 本地模型内存峰值 | 加载 `qwen2.5:3b` 推理时 | **11.4 GB**（16GB 机器，可用 4.2GB） | CPU 占用仅 11%：**内存密集型**，非计算密集型 |

**结论**：本地兜底是**可用性**方案而不是**性能**方案；把 3B 模型用作降级引擎的前提是机器有 12GB+ 可用内存。

---

## 三个核心工程问题的处置

### 1. 模型不可用 → 生成阶段主备降级 + 快速失败

- `auto` 模式：主引擎失败即切本地 Ollama（`src/rag_demo.py`）；
- 显式 `max_retries=0`：**不做内部重试**，让降级在秒级发生而不是卡住；
- `--engine zhipu` / `--no-fallback`：宁可立刻失败也不静默降级，并把失败原因编码成退出码（2 = 主引擎不可用 / 3 = 主备均不可用），便于脚本与 CI 断言。

### 2. 向量空间错配 → 元数据一致性守卫 + 一条命令修复

不同 Embedding 模型（智谱 2048 维 / Ollama 768 维）写进同一个集合会导致检索静默返回错乱结果。
处置方式：建库时把 `embedder` 写进集合元数据，查询前比对；不一致就**拒绝检索**并给出可直接执行的重建命令。

```bash
python src/rag_demo.py --embedder zhipu  --rebuild   # 切到云端向量
python src/rag_demo.py --embedder ollama --rebuild   # 切到本地向量
```

### 3. 协议线污染 → stdout/stderr 纪律 + 可复现故障的探针

stdio 传输下 **stdout 就是 JSON-RPC 协议线**：服务端任何 `print()` 都会搅乱报文，表现为「握手卡住 / 客户端解析失败」。
处置方式：服务端日志一律 `logging → stderr`；并提供一个**可以主动复现该故障**的旁路探针，把「靠猜」变成一条命令。

```bash
python src/mcp_demo/mcp_protocol_probe.py                 # 正常：三步全绿，退出码 0
python src/mcp_demo/mcp_protocol_probe.py --break-stdout  # 负向：稳定复现 + 结构化定位，退出码 4
```

探针退出码：`0` 正常 · `1` 参数/路径错误 · `2` 缺 mcp SDK · `3` 环境限制 · `4` 协议层失败。

---

## 测试与自检

```bash
python -m unittest discover -s tests -v   # 纯标准库单元测试（不需要第三方依赖）
python tests/run_all.py                   # 同一套测试的脚本入口（受限环境不能用 python -m 时用）
python scripts/import_check.py            # 跨目录 import + 路径常量自检
python scripts/health_check.py            # 全量自检：目录/硬编码路径/导入/路径边界/启动烟雾
```

测试覆盖（52 个用例）：

| 文件 | 防的是什么回归 |
|---|---|
| `tests/test_paths.py` | 项目根定位静默指错目录；凭据脱敏被改坏；公共模块导出清单漏项 |
| `tests/test_router.py` | 关键词路由与「到日语 / to Russian」解析被改坏 |
| `tests/test_rag_scoring.py` | 关键词权重、IDF 打分、双路召回去重合并、融合公式与排序 |
| `tests/test_security_masking.py` | 凭据再次被打进公网页面（源码级断言） |
| `tests/test_probe_contract.py` | 探针退化成只会走 happy path；污染开关默认被打开 |

CI：`.github/workflows/ci.yml` 在 Python 3.10 / 3.12 上跑单元测试 + 导入自检。

**自检的三态语义**（避免「假绿」）：退出码 0 = 通过；已声明业务语义的非零码（如 `query_student` 的 `1` = 用了 mock 数据）= **WARN，不计为健康**；未声明的非零码 = FAIL。

---

## 已知限制

诚实清单 —— 这些都是**尚未完成**的能力，不要按已完成理解：

1. **检索侧没有降级**：降级只覆盖生成阶段。智谱 **Embedding** 接口不可用时，检索会直接失败退出（不会自动切本地向量）。这是当前最该补的缺口。
2. **没有退避 / 抖动 / 熔断 / 时间预算**：实现的是一次主备切换 + 快速失败，不是完整的容错链路。
3. **多智能体模块是确定性演示实现**：内置小知识库 + 规则评审，用来讲清 Agent Loop 的状态流转与止损；未接入真实向量库与 LLM 评审。
4. **没有 RAG 量化评测**：hit@k / MRR / 答案命中率 / Token 成本尚未做成评测脚本；[实测数据](#实测数据含测量口径)是单次运行值而非评测集指标。
5. **端到端测试受环境限制**：CI 跑纯标准库单测与导入自检；MCP 端到端用例在无法创建子进程管道的受限沙箱里会**明确 SKIP**。
6. **Docker 镜像内没有 Ollama**：容器里 `OLLAMA_BASE_URL` 默认指向 `localhost:11434`，也就是容器自己 —— 想在容器里演示降级，需要另起 Ollama 容器并改 `OLLAMA_BASE_URL`。
7. **MCP 探针未断言控制帧**：`initialized` 通知、`ping`、`progress`、`cancellation` 等尚未逐项断言，只覆盖客户端三步主链路。
8. **公网 Demo 的模块 ③/⑤ 在无 MongoDB 时走 mock**：会明确标注 `[mock]` 且页面提示「这是演示数据」，需要真实数据请配置 `MONGO_URI`（推荐 MongoDB Atlas）并把 `STUDENT_ALLOW_MOCK=false` 切到严格模式。
9. **英文版 README_EN.md 尚未同步本轮改动**（命令仍是旧目录结构）。

---

## 部署

### Streamlit Cloud（主路径）

1. 推送仓库 → <https://share.streamlit.io> → **New app**；
2. **Main file path 填 `streamlit_app.py`**（不要填 `src/ui/dashboard.py`）；
3. Python 版本建议 3.12；
4. `Settings → Secrets` 填 `ZHIPU_API_KEY`，需要真实数据再加 `MONGO_URI` / `MONGO_DB` / `MONGO_COLLECTION`；
5. 保存后 **Reboot app**。

详细排错对照表见 [DEPLOY.md](DEPLOY.md)，目录与命令对照见 [DEPLOY_STRUCTURE.md](DEPLOY_STRUCTURE.md)。

### 自建容器

```bash
docker build -t ai-agent-harness .
docker run --rm -p 8501:8501 \
  -e ZHIPU_API_KEY="sk-xxxx" \
  -e MONGO_URI="mongodb://host.docker.internal:27017/" \
  ai-agent-harness
# 浏览器打开 http://localhost:8501
```

镜像基于 `python:3.12-slim`，密钥只走 `-e` / `--env-file`，`.dockerignore` 已排除 `.env` 与 `secrets.toml`。
⚠️ 镜像内**没有 Ollama**（见[已知限制](#已知限制)第 6 条）。

---

## 目录结构

```
AI-Agent-Harness/
├─ streamlit_app.py            # ★ 部署入口（Streamlit Cloud 的 Main file path 填它）
├─ requirements.txt
├─ README.md                   # 本文件
├─ LICENSE                     # MIT
├─ DEPLOY.md                   # 云端部署与报错对照表
├─ DEPLOY_STRUCTURE.md         # 目录重构说明与命令对照
├─ Dockerfile / .dockerignore
├─ .github/workflows/ci.yml    # CI：单元测试 + 导入自检
├─ src/
│  ├─ paths.py                 # ★ 唯一路径 / 环境变量中心（含 mask_uri / mask_secrets）
│  ├─ rag_demo.py              # ① RAG：改写 + 混合检索 + 双引擎降级
│  ├─ multi_agent_demo.py      # ② 多智能体：LangGraph 状态图 + 防死循环
│  ├─ core/                    # ③ 路由 ⑤ Function Calling + MongoDB 工具
│  ├─ mcp_demo/                # ④ MCP 服务端 / 客户端 / 旁路探针
│  └─ ui/dashboard.py          # Streamlit 页面实现
├─ data/
│  ├─ knowledge_base.txt       # RAG 知识库原文
│  ├─ chroma_db/               # 向量库（随仓库提交，云端冷启动无需重建）
│  └─ test.db                  # 示例 SQLite（legacy JS 脚本使用）
├─ docs/
│  ├─ PITFALLS.md              # ★ 19 段踩坑与排错复盘
│  └─ images/                  # ★ 44 张实测截图（01~44）
├─ tests/                      # 52 个纯标准库用例 + fixtures
└─ scripts/                    # 自检、导入检查、legacy JS 脚本
```

---

## 安全约定

- `.env` 与 `.streamlit/secrets.toml` 已被 `.gitignore` 忽略，**绝不提交**；
- 密钥只通过 `os.environ` 读取，**不打印、不回显、不写日志**；
- 需要打印连接串时**必须**经过 `paths.mask_uri()`——只保留 scheme / 主机 / 库名：

  ```python
  from paths import mask_uri
  print(f"[mock] 未能连接 MongoDB（{mask_uri(MONGO_URI)}），已返回模拟数据。")
  # mongodb+srv://***:***@cluster0.xxx.mongodb.net/?retryWrites=true
  ```

- Streamlit 页面渲染子进程输出前统一过 `paths.mask_secrets()`（连接串 / `sk-` Key / `Bearer` 令牌 / `key=value`），
  因为页面是**公网**的，子脚本或第三方库一旦把环境变量打进日志就会泄露；
- 若仓库里出现看起来像真实 Key 的字符串，请立即轮换。

---

## 踩坑复盘（19 段）

从沙箱拦截、模型代码幻觉、字符集编码冲突，到向量空间冲突、双引擎容灾演练、MCP 协议线污染，
完整的过程记录与 44 张实测截图在 **[docs/PITFALLS.md](docs/PITFALLS.md)**。

---

## 后续规划

- [ ] **检索侧降级**：Embedding 接口不可用时自动切本地向量或已建索引（当前最大缺口）
- [ ] 容错链路补全：指数退避 + 抖动 + 熔断 + 总时间预算 + 幂等 `request_id`
- [ ] RAG 评测集与指标：`hit@k` / `MRR` / 答案命中率 / Token 成本，做成一条命令出对比表
- [ ] 多智能体接入真实向量库与 LLM 评审，输出「第 1 轮 vs 第 2 轮」召回提升
- [ ] MCP 探针补控制帧断言（`initialized` / `ping` / `progress` / `cancellation`）
- [ ] CI 增加可选的全量依赖任务（跑 MCP 端到端负向用例）
- [ ] 同步 `README_EN.md`，并补 `docker-compose.yml`（app + ollama，让容器内降级可用）

---

## License

[MIT](LICENSE) © 2026 Rundong Yang
