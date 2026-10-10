# 实战踩坑与排错复盘（PITFALLS）

> 本文是 AI-Agent-Harness 的**过程记录**：19 段真实踩坑、定位与修复。
> 项目定位、架构、快速开始与已知限制见根目录的 [README.md](../README.md)。
> 截图统一放在 `docs/images/`（编号与正文一一对应）。

这些记录的价值不在「故事好听」，而在于每一段都给出了**可复现的现象 + 定位手段 + 最终修复**。
面试/评审时建议按「现象 → 怎么定位 → 修了什么 → 怎么防止再犯」四步走。

---

## 1. 沙箱环境限制与工具重构

* **现象**：Harness 沙箱拦截了 Python 解释器的外部调用，报错 `file access denied`。
* **解决**：顺应沙箱的安全规则，把工具重构为 Node.js 内置环境，兼顾安全性与执行效率。

![沙箱拦截](images/01-sandbox-denied.png?raw=true)

## 2. 轻量级模型代码幻觉与自我纠错失败

* **现象**：智谱 GLM-4-Flash 生成 Node.js 脚本时，错误地对字符串使用了对象解构赋值（`const { id } = '1002'`），导致参数变成 `undefined`，任务失败并产生错误引导（如误报 "Not found"）。
* **现象**：让该模型自我纠错时，它既无法识别逻辑错误，又因端口占用和环境模块隔离（沙箱导致的 `Cannot find module`）彻底放弃。
* **解决**：通过查看 Trace（轨迹）日志精准定位到参数异常，手动替换为 DeepSeek 后一次跑通，确立了「核心链路调用强推理模型」的策略。

![模型幻觉](images/02-model-hallucination-trace.png?raw=true)
![自我纠错失败](images/03-self-correction-failure.png?raw=true)

## 3. 强推理模型修复与字符集编码排错

* **现象**：DeepSeek 接手后精准修复了代码，但首次请求遇到 PowerShell 默认解码导致的乱码（`aæ...`）。
* **解决**：模型分析出是 `Content-Type: text/plain` 未声明字符集导致，随后添加 `charset=utf-8` 并重启服务，成功获取「李四」；完成后主动执行 `job_kill` 清理后台进程。

![DeepSeek成功](images/04-deepseek-success-trace.png?raw=true)
![修复编码](images/05-deepseek-fix-and-encoding.png?raw=true)
![字符集成功](images/06-charset-utf8-success.png?raw=true)

## 4. 外部 API 集成与合规审批

* **现象**：开发 GitHub Issue 抓取脚本时，需要把英文标题翻译成中文。
* **解决**：Agent 严格遵守 `AGENTS.md` 规则，先输出计划并获得人工批准后才写入文件；同时识别到国内网络对 Google 翻译的限制，改用 MyMemory 免费翻译 API。

![计划审批](images/07-github-issues-plan-approval.png?raw=true)
![外接翻译API](images/08-script-generation-summary.png?raw=true)

## 5. 数据库依赖风险与零依赖改造

* **现象**：创建 SQLite 数据库时，Agent 原本计划使用 `better-sqlite3`，但它在 Windows 下属于原生 C++ 模块，存在编译失败风险。
* **解决**：我果断介入要求改方案。Agent 检查 Node 版本（v24.21.0）后改用内置的 `node:sqlite` 模块，成功建表、插入数据并查询出 `id=2` 的学生为「李四」，实现零外部依赖部署。

![数据库选型](images/09-database-sqlite-setup.png?raw=true)
![执行验证](images/10-sqlite-execution-and-verification.png?raw=true)

## 6. 生成与执行解耦（混合工作流闭环）

* **现象**：由于 Harness 沙箱的安全隔离，Agent 无法直接调用本地 Python 解释器运行脚本；同时 VS Code 静态检查器因为未识别本地解释器，对内置库 `sqlite3` / `os` 误报红线。
* **解决**：采用「生成与执行解耦」的混合工作流：Agent 专注生成代码，我手动拉取到本地 VS Code 并在终端执行 `python query_student.py`，成功输出 `id 为 2 的学生名字是：李四`。代码逻辑得到验证，同时保住了系统安全边界。

![Agent 自动修复编码](images/11-agent-self-correction-trace.png?raw=true)
![本地执行验证成功](images/12-local-execution-verification.png?raw=true)

## 7. 边界测试与参数校验闭环

* **现象**：为了让脚本真正可用，要求 Agent 为 `query_student.py` 增加命令行参数校验，并且必须包含友好的错误提示。
* **解决**：Agent 自主引入 `sys.argv` 与 `parse_id`，并执行 4 组边界测试（无效 ID、正常查询、非数字输入、无参数输入），全部通过；「先审批后执行」「参数化查询防注入」的工程规范落地。

![参数校验闭环](images/13-param-validation-success.png?raw=true)

## 8. 上下文工程反思（元规则与任务规则的解耦）

* **反思**：最初把代码约束（如「用 `sys.argv` 接收参数」）直接写进 `AGENTS.md`，导致 AI 在后续跨领域任务时出现上下文污染与幻觉。
* **解决**：调整为 **「元规则 + 任务规则」** 的分离设计——`AGENTS.md` 只保留全局安全与交互底线（如「先请示再执行」），具体技术约束放在每次对话的 User Prompt 中。上下文更纯净，指令遵循准确率明显提升。

## 9. 多语言自适应翻译路由

* **现象**：最初翻译路由硬编码了 `hello`，且仅支持中英互译，无法处理日语、韩语、俄语等长尾需求。
* **解决**：
  1. 用 `re.finditer` 替代 `re.search`，精准剥离「到日语/到俄语」等后缀，避免「翻译到日语的内容」这类复杂句式误判；
  2. 建立 `LANG_NAME_TO_CODE` 映射表，兼容「日语/日文/chinese」等同义词；
  3. 实现自适应双向翻译（中英互译）与定向多语言路由（中→日/俄/韩）；
  4. 加入同语言保护（源语言 == 目标语言时直接拦截，不发无效请求）与空内容边界处理；
  5. 在本地 VS Code 真实执行 7 组测试用例（含空输入、中英混杂、多语言），全部通过。

![多语言翻译路由验证](images/14-multi-language-router-final.png?raw=true)

## 10. 数据库平滑演进（SQLite → MongoDB）

* **现象**：随着 Agent 工具链复杂化，需要存储动态 JSON 结构与非结构化日志，关系型数据库的严格表结构显得繁琐。
* **解决**：
  1. 用 `pymongo` 重写 `init_db.py` 与 `query_student.py`；
  2. 连接信息严格从环境变量 `MONGO_URI` 读取，避免硬编码（**注意**：打印时必须用 `paths.mask_uri()` 打码，见 README 安全约定）；
  3. 数据以 JSON 文档形式存储，契合 AI 场景数据结构多变的特点；
  4. 本地真实运行：建库、插入 3 条数据、精准查询出 id=2 的「李四」。

![MongoDB 迁移成功](images/15-mongodb-migration-success.png?raw=true)

## 11. RAG 双引擎降级与向量空间隔离实践

* **现象**：为实现数据隐私兜底，设计了云端智谱与本地 Ollama 的双引擎架构。实测遇到 `Collection expecting embedding with dimension of 2048, got 768` 的向量空间冲突；另外故意注入无效 Key 时，系统需要自动降级。

![向量空间冲突报错](images/16-vector-dimension-conflict-error.png?raw=true)

* **解决**：
  1. 在代码中加入 `embedder` 元数据校验：切换 Embedding 引擎时**拒绝**在旧向量空间上检索，并提示执行 `--rebuild` 重建向量库，避免返回语义错乱的垃圾结果；
     ![重建向量库成功](images/17-ollama-rebuild-success.png?raw=true)
  2. 设计 try/except 降级机制：智谱返回 401 鉴权错误或超时时，自动切换至本地 Ollama 3B；
  3. 实测纯 CPU 环境下本地模型推理耗时 71.1s，虽慢但保住了断网环境下的可用性。
     ![Ollama降级成功](images/18-rag-fallback-ollama.png?raw=true)

> 说明：2048 / 768 这两个维度值来自报错信息与两个引擎的已知规格，代码里**不做维度探测**，
> 判定依据是建库时写入的 `embedder` 元数据。「检索侧未做降级」属已知限制，见 README。

## 12. 双引擎容灾演练与资源占用实测

* **现象**：为了验证容灾路径，做了两组真实测试。第一次不加参数运行，智谱因网络波动超时，系统自动降级到本地 Ollama（72 秒成功返回）；第二次强制 `--engine zhipu`，智谱再次超时，系统严格执行「快速失败」，报错退出并拒绝降级。

![自动降级成功](images/19-rag-auto-fallback-success.png?raw=true)
![严格模式快速失败](images/20-rag-strict-mode-fail-fast.png?raw=true)

* **解决与反思**：
  1. 验证了 `auto` 模式下的主备切换：外部 API 故障时仍能输出；
  2. 验证了 `--engine zhipu` 的 Fail-fast：核心链路宁可立刻暴露问题，也不静默降级；
  3. 实测本地 Ollama 的硬件开销：16GB 内存机器加载 qwen2.5-3b 推理时内存峰值 11.4GB（可用 4.2GB），CPU 占用仅 11% —— 本地推理是**内存密集型**而非计算密集型，对硬件有明确要求。

![本地Ollama内存占用](images/21-ollama-local-memory-usage.png?raw=true)

## 13. RAG 系统边界测试与容灾机制

1. **快速失败（Fail-fast）**
   * **现象**：模拟智谱 API 超时，并明确指定 `--no-fallback` 禁止降级。
   * **解决**：系统立即捕获异常并以退出码 2 结束。适用于「必须使用高精度模型、严禁劣质降级」的核心链路。
     ![快速失败机制](images/22-fail-fast.png?raw=true)
2. **知识库热更新与索引重建**
   * **现象**：知识库从 181 个片段增长到 362 个片段。
   * **解决**：`python src/rag_demo.py --rebuild` 丢弃旧索引，重新切分并向量化 362 个片段，耗时 6.2s。
     ![索引重建](images/23-rebuild-362-chunks.png?raw=true)
3. **全离线隐私模式**
   * **现象**：断网或数据涉密场景需要完全切断云端 API。
   * **解决**：`--engine ollama --embedder ollama` 让全链路走本地模型（Qwen2.5-3B + nomic-embed-text），实测纯 CPU 生成耗时 47.8s。
     ![全离线模式](images/24-fully-offline.png?raw=true)
4. **CLI 容灾参数矩阵**
   * 命令行覆盖常规运行、强制云端、全离线、禁用降级、仅重建索引等场景。
     ![CLI参数矩阵](images/25-cli-matrix.png?raw=true)

## 14. 多引擎混合调度（检索与生成解耦）

1. **本地 Ollama 建库与向量检索**
   * **现象**：为避免云端 API 限流导致建库失败，使用 `--embedder ollama --rebuild` 在本地重建向量库。
   * **解决**：实测 181 个片段纯 CPU 向量化耗时 73.8s；提问时本地检索 4 个片段仅 0.06s。
     ![Ollama本地建库与检索](images/26-ollama-rebuild-and-retrieve.png?raw=true)
2. **检索与生成的交叉解耦与上下文注入**
   * **现象**：用 `--show-prompt` 打印最终 Prompt，确认代码把 Top-K 片段、系统角色规则与用户问题拼成了「开卷参考资料」。
   * **解决**：拼好的 Prompt 交给智谱 glm-4-flash 生成（实测 20.1s）——「谁查资料（本地 Ollama）」与「谁写报告（云端智谱）」可独立解耦与动态调度。
     ![Ollama检索与智谱生成](images/27-ollama-retrieval-zhipu-generation.png?raw=true)
     ![上下文注入与Prompt拼接](images/28-rag-show-prompt-context.png?raw=true)

## 15. 多智能体协作与 Agent Loop 防死循环（LangGraph）

* **现象**：普通 RAG 是一次性线性检索，缺乏自我反思与重试；而企业级 Agent 需要「规划-执行-审查-重试」的循环，又必须严格防止死循环。
* **解决**：
  1. 基于 `langgraph` 的 `StateGraph` 构建 `Retriever`（检索）与 `Reviewer`（审查）两个协作 Agent；
  2. 用**条件边**实现打回重试：Reviewer 认为资料不达标时，把 `feedback` 回传给 Retriever 深挖邻居文档；
  3. 设计防死循环止损：`retry_count` 超过 2 次仍未通过则触发 `give_up` 安全退出，另有 `recursion_limit` 作为硬保护；
  4. 实测 3 组用例，覆盖「一次通过 / 打回后通过 / 重试耗尽安全退出」，断言全部符合预期。

![多智能体协作与防死循环](images/29-multi-agent-loop.png?raw=true)

> 覆盖边界：本模块的检索与审查为**确定性演示实现**（内置小知识库 + 规则评审），
> 目的是把 Agent Loop 的状态流转与止损讲清楚，未接入真实向量库与大模型评审。

## 16. Function Calling 与工具封装（LangChain）

* **现象**：大模型无法直接操作外部数据库，需要标准化的工具调用机制实现「大脑指挥手脚」。
* **解决**：
  1. 用 LangChain 的 `@tool` 装饰器把底层 MongoDB 查询封装成 `query_student_info`；
  2. **工具永不抛异常**：查不到、连不上都返回结构化 JSON 作为「观察结果」，防止 Traceback 炸掉整个 Agent；
  3. Agent 能根据自然语言自动抽取参数（如 `{"student_id": 3}`）并发起原生 Tool Calling；
  4. 终端日志完整展示 `HumanMessage → AIMessage(决策) → ToolMessage(执行) → AIMessage(回答)` 的 ReAct 闭环。

![Function Calling 实践](images/30-function-calling-demo.png?raw=true)

## 17. MCP（Model Context Protocol）跨进程工具调用实践

* **现象**：普通 Function Calling 只能调用本进程内的 Python 函数；要复用外部工具（IDE、Claude Desktop、其他语言写的服务）就需要标准协议。落地 stdio 模式时踩到两个坑：
  1. 直接运行 `python src/mcp_demo/mcp_weather_server.py` 终端「卡住」，没有任何输出；
  2. 官方推荐的 `mcp dev` 可视化面板报错 `Failed`，右侧控制台出现乱码。
* **解决**：
  1. **理解 stdio 传输的底层机制**：Server 启动后并非卡死，而是盯着 `stdin` 等客户端发 JSON-RPC 报文；直接运行挂起是正确行为，`Ctrl+C` 退出即可。
  2. **放弃不可用的可视化工具，改用旁路探针**：`mcp dev` 在 Windows 下依赖 `uv` 包管理器导致水土不服，于是退回命令行编写了 `mcp_protocol_probe.py`（绕开 LangChain，但不绕开官方 SDK），把 `initialize` / `tools/list` / `tools/call` 三个阶段的实际结果摊开，确认协议层通信正常。
  3. **严格规范日志输出**：踩过「卡住」的坑后形成纪律——stdio 传输下 **`stdout` 就是协议线，严禁 `print()`**，服务端日志一律通过 `logging` 输出到 `stderr`，否则报文被污染，客户端直接解析失败或卡死。
  4. **完成 MCP 集成**：通过 LangChain 的 MCPAdapter 连接本地 Server，实现大模型自动提取参数、跨进程调用天气工具并输出最终回答。
* **核心文件**：
  * `src/mcp_demo/mcp_weather_server.py`：MCP Server（stdio），提供模拟天气工具，日志全程走 stderr；内置 `MCP_POLLUTE_STDOUT=1` 开关**专门用于复现 stdout 污染**（默认关闭）。
  * `src/mcp_demo/mcp_weather_client.py`：LangChain 客户端，用 MCPAdapter 拉取工具并让大模型自动调用。
  * `src/mcp_demo/mcp_protocol_probe.py`：旁路探针。除正常三步验证外，支持 `--break-stdout` **稳定复现**协议线被污染导致的通信中断，并输出结构化定位结论（退出码 2/3/4 分别表示缺 SDK / 环境限制 / 协议层失败）。
* **本地验证**：先用探针验证协议层，再用客户端验证大模型调用，最终输出「北京：晴，25度（北风 3 级，湿度 40%）」。

![MCP 协议探针 - 初始化与工具列表](images/31-mcp-probe-initialize-list.png?raw=true)
![MCP 协议探针 - 工具调用](images/32-mcp-probe-tools-call.png?raw=true)
![MCP 大模型调度](images/33-mcp-weather-demo.png?raw=true)
![MCP 可视化工具失败排查](images/34-mcp-inspector-failed.png?raw=true)

> 复现命令：`python src/mcp_demo/mcp_protocol_probe.py --break-stdout`
> 覆盖边界：探针断言的是客户端三步主链路，`initialized` 通知、`ping`、`progress`、`cancellation`
> 等控制帧尚未逐一断言（见 README 已知限制）。

## 18. RAG 进阶优化：Query Rewrite 与混合检索

针对基础向量检索在口语化提问下召回率低的问题，实现了查询改写（Query Rewrite）与混合检索（Hybrid Search），并用对照实验验证效果：

* **默认优化链路（Query Rewrite + Hybrid Search）**
  调用 `glm-4-flash` 把「我的VPN坏了」改写为「VPN 连接故障」并抽取关键词，执行双路召回（改写词 + 原问题），最终得分 `0.7×向量 + 0.3×关键词`。实测 Top-1 精准命中 VPN 相关文档。
  ![查询改写与混合检索](images/35-rag-query-rewrite-hybrid-search.png?raw=true)
  ![混合检索后的Context与回答](images/36-rag-context-after-hybrid-search.png?raw=true)
* **对照组 A（纯向量检索，`--no-rerank`）**
  关闭改写与关键词重排后，向量模型认为「VPN坏了」与「DNS解析失败」语义相似，把错误文档排到首位，召回质量明显下降。
  ![纯向量检索对照组](images/37-rag-baseline-no-rerank.png?raw=true)
* **对照组 B（仅本地关键词加分，`--no-rewrite`）**
  关闭云端改写，仅靠本地分词提取「VPN」并赋 1.0 权重，依然能把正确文档顶到 Top-1 —— 说明**没有云端改写时降级链路仍然可用**。
  ![本地关键词加分对照组](images/38-rag-no-rewrite-local-keyword.png?raw=true)
* **防幻觉验证**
  知识库未收录解决方案时，系统遵守 Prompt 约束直接回复「知识库中未收录该信息，建议联系 IT 服务台」，没有让模型凭直觉编答案。

> 口径说明：以上对照为同一知识库、同一问题的单次实测截图对比，**未做多次平均与统计显著性检验**；
> 定量评测（hit@k / MRR / 延迟 / Token 成本）在 README 的后续规划中。

## 19. 统一 Web 控制台（Agent Operations Console）

基于 Streamlit 构建统一控制台，通过 `subprocess` 跨进程调度五个核心模块，支持动态调节超时、模型引擎与检索参数，统一用 UTF-8 捕获子进程输出：

1. **RAG 知识库问答**：查询改写、混合检索、防幻觉验证，全链路打分可视化；
2. **多智能体协作演示**：展示 LangGraph 状态图的 `retry_count` 打回重试与安全退出；
3. **多模型路由**：自然语言指令自动路由到本地脚本、免费翻译 API 或 DeepSeek；
4. **MCP 协议探针**：把 `initialize` / `tools/list` / `tools/call` 的结果投射到网页；
5. **Function Calling 演示**：LangChain `@tool` 封装 MongoDB 查询，让模型自动抽参调用。

### 控制台运行实况

![统一控制台主界面](images/39-web-console-rag.png?raw=true)

* **① RAG 知识库问答**：输入「我的账号不行了」，自动改写为「账号无法登录」，混合检索（向量 0.7 + 关键词 0.3）精准召回。
  ![RAG 混合检索](images/40-web-console-rag-hybrid-search.png?raw=true)
* **② 多智能体协作演示**：Retriever 与 Reviewer 协作，展示 `retry_count` 从 0 到 2 与 `give_up` 安全退出，断言全部符合预期。
  ![多智能体状态流转](images/41-web-console-multi-agent-loop.png?raw=true)
* **③ 多模型路由**：输入「翻译多模型 为俄语」，路由到免费翻译 API，返回 `Мультимодель перевода`。
  ![多模型路由](images/42-web-console-router-translate.png?raw=true)
* **④ MCP 协议探针**：点击按钮，网页上投射 `initialize` 握手与 `tools/call` 的原始报文（广州天气）。
  ![MCP协议探针](images/43-web-console-mcp-probe.png?raw=true)
* **⑤ Function Calling 演示**：提问「帮我查一下学号是 3 的学生叫什么名字？」，模型自动抽取 `{"student_id": 3}` 并发起原生工具调用，日志展示完整 ReAct 闭环。
  ![Function Calling 控制台演示](images/44-web-console-function-calling.png?raw=true)

---

## 最后：这套复盘的真正产出

1. 掌握了基于 Trace（轨迹）定位 AI 工具调用失败原因的方法；
2. 理解了沙箱隔离、文件系统观察策略对 Agent 安全的意义；
3. 形成了「AI 生成 + 本地 IDE 验证」的混合工作流，把生成与执行解耦；
4. 具备了对 AI 生成代码做工程审查（防注入、资源释放、异常捕获）的实战能力；
5. 理解了检索与生成解耦架构，以及向量空间冲突、API 限流、断网等极端情况下的容灾降级。
