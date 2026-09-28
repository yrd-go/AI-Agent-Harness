# My-Agent-Debugger (Agent 工具链排错与混合工作流实战记录)

## 💡 项目背景
本项目是一个软件工程学生的 **AI Agent 落地实战记录**。在基于 DeepSeek Harness 搭建本地工具链时，我真实经历了沙箱隔离、大模型代码幻觉、Windows 环境编码冲突等工程痛点。我通过 Trace 轨迹分析、多模型 A/B 对比、以及“生成与执行解耦”的混合工作流，最终跑通了从 Node.js 到 Python 的数据库查询闭环。
本仓库记录了完整的排查思路、对比截图与代码演进过程，旨在分享 AI 时代“AI 辅助生成”与“人类工程审查”结合的最佳实践。

## 🚀 快速复现与运行指南
### 前置要求
*   Node.js >= 22.5.0（原生支持 `node:sqlite`）
*   Python >= 3.10
*   各大模型 API Key（DeepSeek / 智谱 GLM 等）
*   本仓库中的 `test.db` 数据库由 `init_db.js` 自动生成，请先执行初始化

### 运行演示脚本
1. **Node.js 版本（数据库初始化与查询）**：
   ```bash
   node init_db.js
   node query_student.js 2
   ```
2. **Python 版本（参数校验与异常捕获）**：
   ```bash
   python query_student.py 2
   python query_student.py abc
   python query_student.py
   ```
*注：本仓库根目录包含 Node.js 和 Python 混合验证脚本，分别对应不同阶段的排错实验。*

## 🔍 实战踩坑与解决案例

### 1. 沙箱环境限制与工具重构
* **现象**：Harness 沙箱拦截了 Python 解释器的外部调用，报错 `file access denied`。
* **解决**：顺应沙箱的安全规则，将工具重构为 Node.js 内置环境，兼顾了安全性与执行效率。
  ![沙箱拦截](01-sandbox-denied.png?raw=true)

### 2. 轻量级模型代码幻觉与自我纠错失败
* **现象**：智谱 GLM-4-Flash 生成 Node.js 脚本时，错误地对字符串使用了对象解构赋值（`const { id } = '1002'`），导致参数变成 `undefined`，最终任务失败并产生错误引导（如误报“Not found”）。
* **现象**：让该模型尝试自我纠错时，它既无法识别逻辑错误，又因端口占用和环境模块隔离（沙箱导致的 `Cannot find module`）彻底放弃。
* **解决**：通过查看 Trace（轨迹）日志精准定位到参数异常，手动替换为 DeepSeek 后一次跑通，确立了“核心链路调用强推理模型”的策略。
  ![模型幻觉](02-model-hallucination-trace.png?raw=true)
  ![自我纠错失败](03-self-correction-failure.png?raw=true)

### 3. 强推理模型修复与字符集编码排错
* **现象**：DeepSeek 接手后精准修复了代码，但首次请求时遇到 PowerShell 默认解码导致的乱码（`aæ...`）。
* **解决**：模型主动分析出是 `Content-Type: text/plain` 未声明字符集导致，随后添加 `charset=utf-8` 并重启服务，成功获取“李四”。完成后还主动执行 `job_kill` 清理了后台进程，展现了优秀的资源生命周期管理能力。
  ![DeepSeek成功](04-deepseek-success-trace.png?raw=true)
  ![修复编码](05-deepseek-fix-and-encoding.png?raw=true)
  ![字符集成功](06-charset-utf8-success.png?raw=true)

### 4. 外部 API 集成与合规审批
* **现象**：在开发 GitHub Issue 抓取脚本时，需要将英文标题翻译为中文。
* **解决**：Agent 严格遵守 `AGENTS.md` 规则，先输出计划并获得人工批准后才写入文件。同时，它识别到国内网络环境对 Google 翻译的限制，成功集成了 MyMemory 免费翻译 API。
  ![计划审批](07-github-issues-plan-approval.png?raw=true)
  ![外接翻译API](08-script-generation-summary.png?raw=true)

### 5. 数据库依赖风险与零依赖改造
* **现象**：创建 SQLite 数据库时，Agent 原本计划使用 `better-sqlite3`，但这在 Windows 下属于原生 C++ 模块，存在编译失败风险。
* **解决**：我果断介入，要求修改方案。Agent 随即检查 Node 版本（v24.21.0），改用内置的 `node:sqlite` 模块。最终成功建表、插入数据并查询出 `id=2` 的学生为“李四”，实现了零外部依赖部署。
  ![数据库选型](09-database-sqlite-setup.png?raw=true)
  ![执行验证](10-sqlite-execution-and-verification.png?raw=true)

### 6. 生成与执行解耦（混合工作流闭环）
* **现象**：由于 Harness 沙箱的安全隔离，Agent 无法直接调用本地 Python 解释器运行脚本；同时 VS Code 静态检查器因为未识别本地解释器，对内置库 `sqlite3` 和 `os` 误报红线。
* **解决**：我采用了“生成与执行解耦”的混合工作流。让 Agent 专注生成代码，我则手动拉取代码到本地 VS Code，并在终端执行 `python query_student.py`，成功输出 `id 为 2 的学生名字是：李四`。这验证了代码逻辑的正确性，同时保证了系统的安全边界。
  ![Agent 自动修复编码](11-agent-self-correction-trace.png?raw=true)
  ![本地执行验证成功](12-local-execution-verification.png?raw=true)

### 7. 边界测试与参数校验闭环
* **现象**：为了让脚本真正可用，我要求 Agent 为 `query_student.py` 增加命令行参数校验，并且必须包含友好的错误提示。
* **解决**：Agent 自主引入了 `sys.argv` 和 `parse_id` 函数，并主动执行了 4 组边界测试（无效 ID、正常查询、非数字输入、无参数输入），全部通过。这验证了我在 `AGENTS.md` 中设定“先审批后执行”以及“参数化查询防 SQL 注入”的工程规范完全落地。
  ![参数校验闭环](13-param-validation-success.png?raw=true)

### 8. 上下文工程反思（元规则与任务规则的解耦）
* **反思**：最初我将代码约束（如“用 `sys.argv` 接收参数”）直接写进 `AGENTS.md`，导致 AI 在后续跨领域任务时产生了上下文污染和幻觉。
* **解决**：我将架构调整为 **“元规则 + 任务规则”** 的分离设计：`AGENTS.md` 仅保留全局安全与交互底线（如“先请示再执行”），具体的技术约束放在每次对话的 User Prompt 中。这不仅保证了系统上下文纯净，也大幅提升了 AI 的指令遵循准确率。

### 9. 多语言自适应翻译路由
* **现象**：最初翻译路由硬编码了 `hello`，且仅支持中英互译，无法处理日语、韩语、俄语等长尾需求。
* **解决**：
  1. 使用 `re.finditer` 替代 `re.search`，精准剥离“到日语/到俄语”等后缀，避免复杂句式（如“翻译到日语的内容”）误判。
  2. 建立 `LANG_NAME_TO_CODE` 映射表，兼容“日语/日文/chinese”等同义词。
  3. 实现**自适应双向翻译**（中英互译）与**定向多语言路由**（中文转日/俄/韩）。
  4. 加入“同语言保护”（源语言==目标语言时直接拦截，不发无效请求）及空内容边界处理。
  5. 在本地 VS Code 真实执行了 7 组测试用例（含空输入、中英混杂、多语言），全部通过。
  ![多语言翻译路由验证](14-multi-language-router-final.png?raw=true)

### 10. 数据库平滑演进（SQLite -> MongoDB）
* **现象**：随着 Agent 工具链复杂化，需要存储动态 JSON 结构和非结构化日志。关系型数据库（SQLite/MySQL）的严格表结构显得繁琐。
* **解决**：我主导了数据库选型变更，从 SQLite 迁移到文档型数据库 **MongoDB**。
  1. 使用 `pymongo` 库重写 `init_db.py` 和 `query_student.py`。
  2. 连接信息严格从环境变量 `MONGO_URI` 读取，避免硬编码。
  3. 数据以 JSON 文档格式存储（`{"id": 1, "name": "张三"}`），契合 AI 领域数据结构多变的特性。
  4. 在本地 VS Code 真实运行，成功建库、插入 3 条数据并精准查询出 id=2 的“李四”。
  ![MongoDB 迁移成功](15-mongodb-migration-success.png?raw=true)

### 11. RAG 双引擎降级与向量空间隔离实践
* **现象**：为了实现数据隐私兜底，我设计了云端智谱与本地 Ollama 的双引擎架构。但在实际测试中遇到了 `Collection expecting embedding with dimension of 2048, got 768` 的向量空间冲突问题，且故意注入无效 Key 时系统需要自动降级。
  ![向量空间冲突报错](16-vector-dimension-conflict-error.png?raw=true)
* **解决**：
  1. 在代码中加入严格的 `embedder` 元数据校验，若切换 Embedding 引擎，强制要求 `--rebuild` 重建向量库，防止返回语义错误的垃圾结果。
     ![重建向量库成功](17-ollama-rebuild-success.png?raw=true)
  2. 设计 `try-except` 降级机制。当智谱 API 返回 401 鉴权错误或超时时，自动捕获异常并切换至本地 Ollama 3B 模型。
  3. 实测在纯 CPU 环境下，本地模型推理耗时 48.7s，虽然较慢，但完美保证了断网环境下的系统可用性。

     ![Ollama降级成功](18-ollama-fallback-success.png?raw=true)
## 🚀 核心收获
1. 掌握了基于 Trace（轨迹）定位 AI 工具调用失败原因的方法。
2. 体验并理解了本地沙箱隔离、文件系统观察策略（`FS_NOT_OBSERVED`）对 Agent 安全的重要性。
3. 掌握了“AI 生成 + 本地 IDE 验证”的混合工作流，实现了生成与执行的安全解耦。
4. 具备了对 AI 生成代码进行工程审查（防 SQL 注入、资源释放、异常捕获）的实战能力。

## 💻 技术栈
* Python (AI 辅助生成与调试)
* Node.js (内置模块开发)
* 大模型 API (DeepSeek / GLM-4-Flash)
* **容器化交付**：提供基于 `python:3.11-slim` 的 `Dockerfile` 与 `.dockerignore`。引入依赖分层缓存优化构建速度，并预留了环境变量注入（`MONGO_URI`）入口，支持 Docker 环境一键部署。
  
## 📈 后续规划
- [ ] 支持自动捕获不同语言（Node.js、Python）的报错堆栈。
- [ ] 实现多模型路由：简单报错用轻量模型，复杂错误路由给强模型降本增效。
