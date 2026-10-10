# AI-Agent-Harness

English | [简体中文](README.md)

**A runnable, high-availability RAG + MCP agent foundation** — with 44 measured screenshots and 20 post-mortems.

[![CI](https://github.com/yrd-go/AI-Agent-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yrd-go/AI-Agent-Harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-green)

Live demo (Streamlit): <https://ai-agent-harness-edjmumadkd9e3lqsmtf3ff.streamlit.app>

> The public demo has no local Ollama and no MongoDB, so modules ③/⑤ run on **explicitly labelled
> mock data**; reproduce the real fallback behaviour locally with the commands below.

![Web console](docs/images/39-web-console-rag.png?raw=true)

### 30-second overview

| | |
|---|---|
| **What it solves** | The four things that break LLM apps in production: model unavailability, vector-space mismatch, **protocol-line pollution**, **embedding endpoint unavailability** |
| **Strongest evidence** | 74 automated tests + green CI; retrieval degrades and answers in **0.29 s** on a 401; MCP protocol failures are **reproducible with one command** |
| **Run it** | `pip install -r requirements.txt` → fill `.env` → `streamlit run streamlit_app.py`<br/>**No API key needed**: `python src/rag_demo.py "my VPN is broken" --keyword-only` |
| **Go deeper** | [Architecture](#architecture) · [Measured data](#measured-data) · [Known limitations](#known-limitations) · [20 post-mortems](docs/PITFALLS.md) |

### Key evidence (screenshots)

| | |
|---|---|
| **Hybrid retrieval scoring**<br/>query rewrite + dual recall + IDF breakdown<br/>![Hybrid search](docs/images/35-rag-query-rewrite-hybrid-search.png?raw=true) | **Cloud API failure → automatic fallback**<br/>Zhipu times out, local Ollama answers (72 s)<br/>![Auto fallback](docs/images/19-rag-auto-fallback-success.png?raw=true) |
| **MCP protocol debugging**<br/>`initialize / tools-list / tools-call` step by step<br/>![MCP probe](docs/images/32-mcp-probe-tools-call.png?raw=true) | **Multi-agent loop**<br/>conditional-edge retry + `give_up` guard<br/>![Multi-agent](docs/images/29-multi-agent-loop.png?raw=true) |

---

## Contents

- [What this is / is not](#what-this-is--is-not)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [The five modules](#the-five-modules)
- [Measured data](#measured-data)
- [Four core engineering problems](#four-core-engineering-problems)
- [Tests and self-check](#tests-and-self-check)
- [Known limitations](#known-limitations)
- [Deployment](#deployment)
- [Project layout](#project-layout)
- [Security conventions](#security-conventions)
- [Post-mortems (20)](docs/PITFALLS.md)
- [Roadmap](#roadmap)

---

## What this is / is not

**What it is**: an engineering foundation that turns the four most common production failure modes of
LLM applications into reproducible, verifiable mitigations — **model unavailability** (dual-engine
generation fallback + fail-fast), **vector-space mismatch** (metadata consistency guard + one-command
rebuild), **protocol-line pollution** (stdout/stderr discipline + a probe that reproduces the fault),
and **retrieval endpoint unavailability** (local keyword-recall fallback with zero external
dependencies). Plus a Streamlit console that wires the five modules together.

**What it is not**: not a model-training/fine-tuning project, and not a high-concurrency production
system. The [known limitations](#known-limitations) are stated honestly — including that the retrieval
fallback is keyword-level (less precise than vector recall), that there is no retry/backoff/circuit
breaker, and that there is no quantitative RAG evaluation yet. Those are the roadmap, not claims.

Stack: Python 3.10+ · LangChain / LangGraph · Chroma · MCP (stdio) · Zhipu GLM-4-Flash · local Ollama · Streamlit · Docker

---

## Quick start

```bash
git clone https://github.com/yrd-go/AI-Agent-Harness.git
cd AI-Agent-Harness

# 1) dependencies (3.11/3.12 recommended; chromadb may lack wheels on 3.14)
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) configuration (.env is never committed; Streamlit Secrets also works)
cp .env.example .env                # Windows: copy .env.example .env
#    minimum: ZHIPU_API_KEY=sk-xxxx
#    optional: MONGO_URI (local mongod or MongoDB Atlas) for real student data

# 3) start the console (same entry point locally and in the cloud)
streamlit run streamlit_app.py
#    open http://localhost:8501
```

**Command line only** (no Streamlit required):

```bash
python src/rag_demo.py "my VPN is broken"                # ① RAG: rewrite + hybrid retrieval + dual-engine generation
python src/rag_demo.py "my VPN is broken" --no-rerank     #    baseline: pure vector retrieval
python src/rag_demo.py --rebuild                         #    rebuild the vector store (required when switching embedder)
python src/rag_demo.py "my VPN is broken" --keyword-only  #    zero-dependency: local keyword recall, no API key at all
python src/rag_demo.py "my VPN is broken" --no-vec-fallback   #  A/B: disable retrieval fallback (fail fast)
python src/multi_agent_demo.py                           # ② multi-agent: agent loop + infinite-loop guard
python src/core/router.py "查学生2"                       # ③ router: local script / free translation API / DeepSeek
python src/mcp_demo/mcp_protocol_probe.py                # ④ MCP probe: three-step protocol check
python src/mcp_demo/mcp_protocol_probe.py --break-stdout  #    ★ negative mode: reproduce stdout pollution
python src/core/agent_tool_demo.py                       # ⑤ function calling: ReAct loop
```

> `.venv-rag/` is the environment name used by the author; scripts auto-detect both `.venv` and
> `.venv-rag` and otherwise fall back to the current interpreter. Always run from the repository root —
> no manual `PYTHONPATH` needed.

---

## Architecture

### ① RAG pipeline: decoupled retrieval/generation, fallback, vector-store consistency guard

```mermaid
graph TD
    Q[User question] --> RW{Query rewrite<br/>glm-4-flash}
    RW -->|ok| HQ[rewritten query + keywords]
    RW -->|failed / no key| OQ[original question + local tokenizer]

    HQ --> VS[(Chroma vector store)]
    OQ --> VS
    VS -->|embedder metadata mismatch| GUARD[refuse retrieval<br/>print --rebuild command]
    VS -->|top-K chunks| FUSE[hybrid scoring<br/>0.7*vector + 0.3*keyword]
    VS -->|embedding endpoint down| KW[local keyword recall<br/>zero external deps]

    FUSE --> GEN[generation engine]
    KW --> GEN
    GEN -->|primary| ZP[Zhipu GLM-4-Flash]
    ZP -->|timeout / rate limit / auth error| FB{fallback}
    FB -->|auto mode| OL[local Ollama Qwen2.5-3B]
    FB -->|--engine zhipu / --no-fallback| FF[fail fast<br/>exit code 2]
    ZP -->|ok| ANS[final answer]
    OL -->|best effort| ANS
```

### ② MCP cross-process tool calling + bypass probe (negative mode included)

```mermaid
graph LR
    LC[LangChain client] -->|MCPAdapter| SRV
    PR[bypass probe<br/>mcp_protocol_probe.py] -->|initialize / tools-list / tools-call| SRV
    PR -.->|--break-stdout<br/>MCP_POLLUTE_STDOUT=1| SRV
    SRV[MCP server subprocess<br/>stdio transport] --> TOOL[get_current_weather]
    SRV -->|stdout = protocol line| LC
    SRV -->|logging to stderr| LOG[logs<br/>never pollute the wire]
    PR -->|protocol failure| DIAG[structured diagnosis + exit code 4]
```

### ③ Multi-agent agent loop (LangGraph state graph)

```mermaid
graph TD
    START --> R[Retriever agent]
    R --> V[Reviewer agent]
    V -->|conditional edge: retry<br/>max 2| R
    V -->|approved| END1[END]
    V -->|give_up<br/>infinite-loop guard| END2[safe exit]
```

### ④ Multi-model routing (send each task to the cheapest adequate tier)

```mermaid
graph LR
    I[natural-language instruction] --> M{keyword match<br/>order = priority}
    M -->|student lookup| A[local script<br/>zero cost]
    M -->|translation| B[free MyMemory API<br/>zero cost]
    M -->|code generation| C[DeepSeek<br/>paid]
    M -->|no match| D[print usage<br/>exit code 1]
```

---

## The five modules

| # | Module | Entry point | Requires | API key |
|---|---|---|---|---|
| ① | RAG QA (rewrite + hybrid retrieval + fallback) | `src/rag_demo.py` | vector store `data/chroma_db/` (committed) | yes (Zhipu) or fully offline (Ollama) |
| ② | Multi-agent collaboration + infinite-loop guard | `src/multi_agent_demo.py` | `langgraph` | no (deterministic demo) |
| ③ | Multi-model routing | `src/core/router.py` | — | only the code-generation route (DeepSeek) |
| ④ | MCP protocol probe (reproducible negative case) | `src/mcp_demo/mcp_protocol_probe.py` | `mcp>=2` | no |
| ⑤ | Function calling (ReAct + tool wrapper) | `src/core/agent_tool_demo.py` | MongoDB (optional; mocks by default) | yes (Zhipu) |

Unified web console: all five modules run from the page, with adjustable timeout / engine / retrieval
parameters and UTF-8-captured output.

---

## Measured data

**Environment**: Windows laptop · 16 GB RAM · **CPU-only inference** (no GPU) · local models
`qwen2.5:3b` + `nomic-embed-text` · cloud models `glm-4-flash` / `embedding-3`
**Caveat**: these are **single-run measurements** (screenshots in [docs/PITFALLS.md](docs/PITFALLS.md)),
**not averages**, and there is no statistical significance testing. Network and server load move these
numbers a lot.

| Scenario | Command | Measured | Notes |
|---|---|---|---|
| Zhipu generation | `python src/rag_demo.py "..."` | 20.1 s | primary engine healthy |
| Auto-fallback to local Ollama | after a Zhipu timeout | 71.1 s / 72 s | availability over speed |
| Fully offline chain | `--engine ollama --embedder ollama` | 47.8 s | never leaves the machine |
| Vector store rebuild | `--embedder ollama --rebuild` | 73.8 s (181 chunks) / 6.2 s (362 chunks, Zhipu) | depends on embedder and chunk count |
| Local vector retrieval | top-K recall | 0.06 s | retrieval is fast; generation is the bottleneck |
| Local model memory peak | loading `qwen2.5:3b` | **11.4 GB** (16 GB machine) | CPU only 11% → memory-bound, not compute-bound |
| **Retrieval fallback** (401 → local keyword recall) | invalid key to force auth failure | **0.29 s** | zero external deps; top-4 were all VPN entries (Q2-01/04/05/03) |

**Conclusion**: the local fallback is an **availability** measure, not a performance one. Running a 3B
model as the degraded engine assumes 12 GB+ of free memory.

---

## Four core engineering problems

### 1. Model unavailable → dual-engine generation fallback + fail-fast

- `auto` mode: switch to local Ollama as soon as the primary engine fails (`src/rag_demo.py`);
- explicit `max_retries=0`: **no internal retries**, so fallback happens in seconds instead of hanging;
- `--engine zhipu` / `--no-fallback`: fail loudly rather than degrade silently, with exit codes
  (2 = primary unavailable / 3 = both unavailable) so scripts and CI can assert on them.

### 2. Vector-space mismatch → metadata guard + one-command rebuild

Writing embeddings from different models (Zhipu 2048-dim / Ollama 768-dim) into one collection makes
retrieval silently return nonsense. Mitigation: store the `embedder` in the collection metadata and
compare it before querying; on mismatch, **refuse to retrieve** and print the exact rebuild command.

```bash
python src/rag_demo.py --embedder zhipu  --rebuild   # switch to cloud vectors
python src/rag_demo.py --embedder ollama --rebuild   # switch to local vectors
```

### 3. Protocol-line pollution → stdout/stderr discipline + a probe that reproduces it

With stdio transport, **stdout is the JSON-RPC wire**: any `print()` in the server corrupts the frames,
which shows up as "handshake hangs / client cannot parse". Mitigation: all server logging goes to
`stderr`, plus a bypass probe that **reproduces the fault on demand** instead of guesswork.

```bash
python src/mcp_demo/mcp_protocol_probe.py                 # healthy: three steps green, exit 0
python src/mcp_demo/mcp_protocol_probe.py --break-stdout  # negative: reproduce + diagnose, exit 4
```

Probe exit codes: `0` ok · `1` bad args/path · `2` mcp SDK missing · `3` environment limit · `4` protocol failure.

### 4. Retrieval unavailable → local keyword-recall fallback (zero external dependencies)

The fallback above only covers **generation**; **retrieval** depends on the cloud embedding endpoint,
and when it times out / rate-limits / the key expires the whole QA path used to fail. Now it degrades to
**local keyword recall**: read every chunk straight from `chromadb` (**no embeddings needed**) and rank
with local IDF scoring (including `tf` and a length penalty), printing an explicit degradation banner so
keyword results are never passed off as vector results.

```bash
python src/rag_demo.py "my VPN is broken"                 # automatic fallback (on by default)
python src/rag_demo.py "my VPN is broken" --no-vec-fallback  # A/B: disable fallback, fail fast
python src/rag_demo.py "my VPN is broken" --keyword-only     # zero-dependency: skip vector store entirely
```

Measured (invalid key forcing a 401): **0.29 s** to answer, top-4 all VPN entries (Q2-01 install /
Q2-04 slow & disconnects / Q2-05 error 691 / Q2-03 intranet access), no external dependency at all.
The debugging story (the fallback initially never triggered, and the ranking degenerated to "all scores
are 1.0") is in [docs/PITFALLS.md §20](docs/PITFALLS.md).

---

## Tests and self-check

```bash
python -m unittest discover -s tests -v   # pure-stdlib unit tests (no third-party deps needed)
python tests/run_all.py                   # same suite as a script (for environments where -m is blocked)
python scripts/import_check.py            # cross-directory imports + path constants
python scripts/health_check.py            # full self-check: layout / hardcoded paths / imports / smoke
```

Coverage (74 tests):

| File | Regression it prevents |
|---|---|
| `tests/test_paths.py` | project root silently pointing at the wrong directory; credential masking broken; stale `__all__` |
| `tests/test_router.py` | keyword routing and "to Russian"-style parsing broken |
| `tests/test_rag_scoring.py` | keyword weights, IDF scoring, dual-recall merge, fusion formula and ordering |
| `tests/test_security_masking.py` | credentials leaking into the public web page (source-level assertions) |
| `tests/test_probe_contract.py` | the probe degenerating into a happy-path-only script |
| `tests/test_import_safety.py` | a module calling `sys.exit` at import time (this once broke the import self-check and CI) |
| `tests/test_retrieval_fallback.py` | retrieval fallback being bypassed (`die()` raises `SystemExit`, not `Exception`); keyword scores collapsing to all-1.0 |

CI: `.github/workflows/ci.yml` runs the unit tests and the import self-check on Python 3.10 and 3.12.

**Three-state self-check semantics** (to avoid false-green): exit code 0 = pass; a non-zero code with a
declared business meaning (e.g. `query_student` returning `1` = "mock data") = **WARN, not counted as
healthy**; any undeclared non-zero code = FAIL. Missing third-party dependencies are reported as
"skipped, unverified" rather than silently passing.

---

## Known limitations

An honest list — these are **not done yet**, do not read them as capabilities:

1. **The retrieval fallback is keyword-level, not vector-level**: it works with zero external deps (401
   and timeout both verified), but tokenization + IDF is weaker than vector recall. A true "vector
   fallback" (local embeddings or cached vectors) is not implemented, and there is no quantitative
   before/after comparison yet (see item 4).
2. **No retry / jitter / circuit breaker / time budget**: what exists is one primary-to-backup switch
   plus fail-fast, not a complete resilience chain.
3. **The multi-agent module is a deterministic demo**: an in-repo mini knowledge base plus rule-based
   review, used to explain state transitions and the give-up guard; it is not wired to a real vector
   store or an LLM reviewer.
4. **No quantitative RAG evaluation**: `hit@k` / `MRR` / answer accuracy / token cost are not yet
   scripted; the [measured data](#measured-data) are single-run numbers, not benchmark metrics.
5. **End-to-end tests are environment-limited**: CI runs pure-stdlib unit tests and the import
   self-check; the MCP end-to-end cases are **explicitly SKIPPED** in sandboxes that forbid child
   process pipes.
6. **The Docker image has no Ollama**: inside the container `OLLAMA_BASE_URL` defaults to
   `localhost:11434`, i.e. the container itself — to demo fallback in Docker, run Ollama separately and
   set `OLLAMA_BASE_URL`.
7. **The MCP probe does not assert control frames**: `initialized` notifications, `ping`, `progress`
   and `cancellation` are not asserted yet; only the three-step client main path is covered.
8. **Modules ③/⑤ use mock data on the public demo when MongoDB is absent**: clearly labelled `[mock]`;
   configure `MONGO_URI` (Atlas recommended) and set `STUDENT_ALLOW_MOCK=false` for real data.

---

## Deployment

### Streamlit Cloud (primary path)

1. Push the repository → <https://share.streamlit.io> → **New app**;
2. **Main file path must be `streamlit_app.py`** (not `src/ui/dashboard.py`);
3. Python 3.12 recommended;
4. `Settings → Secrets`: add `ZHIPU_API_KEY`, plus `MONGO_URI` / `MONGO_DB` / `MONGO_COLLECTION` for real data;
5. **Reboot app** after saving.

See [DEPLOY.md](DEPLOY.md) for the troubleshooting table and [DEPLOY_STRUCTURE.md](DEPLOY_STRUCTURE.md)
for the layout/command mapping.

### Self-hosted container

```bash
docker build -t ai-agent-harness .
docker run --rm -p 8501:8501 \
  -e ZHIPU_API_KEY="sk-xxxx" \
  -e MONGO_URI="mongodb://host.docker.internal:27017/" \
  ai-agent-harness
# open http://localhost:8501
```

The image is based on `python:3.12-slim`; secrets are injected via `-e` / `--env-file` only, and
`.dockerignore` excludes `.env` and `secrets.toml`. ⚠️ The image contains no Ollama (limitation 6).

---

## Project layout

```
AI-Agent-Harness/
├─ streamlit_app.py            # deployment entry point (Streamlit Cloud "Main file path")
├─ requirements.txt
├─ README.md / README_EN.md    # Chinese / English documentation
├─ LICENSE                     # MIT
├─ DEPLOY.md                   # cloud deployment + error lookup table
├─ DEPLOY_STRUCTURE.md         # directory refactor notes and command mapping
├─ Dockerfile / .dockerignore
├─ AGENTS.md                   # AI collaboration rules (meta-level: plan first, secrets via env only)
├─ .github/workflows/ci.yml    # CI: unit tests + import self-check
├─ src/
│  ├─ paths.py                 # ★ single source of truth for paths/env (incl. mask_uri / mask_secrets)
│  ├─ rag_demo.py              # ① RAG: rewrite + hybrid retrieval + dual-engine fallback
│  ├─ multi_agent_demo.py      # ② multi-agent: LangGraph state graph + infinite-loop guard
│  ├─ core/                    # ③ routing, ⑤ function calling, MongoDB tools
│  ├─ mcp_demo/                # ④ MCP server / client / bypass probe
│  └─ ui/dashboard.py          # Streamlit page implementation
├─ data/
│  ├─ knowledge_base.txt       # RAG knowledge base
│  ├─ chroma_db/               # committed vector store (no cold-start rebuild in the cloud)
│  └─ test.db                  # sample SQLite (legacy JS scripts)
├─ docs/
│  ├─ PITFALLS.md              # ★ 20 post-mortems
│  └─ images/                  # ★ 44 measured screenshots (01–44)
├─ tests/                      # 74 pure-stdlib tests + fixtures
└─ scripts/                    # self-checks, import check, legacy JS scripts
```

---

## Security conventions

- `.env` and `.streamlit/secrets.toml` are gitignored and **never committed**;
- secrets are read via `os.environ` only — **never printed, echoed or logged**;
- when a connection string must be printed it **must** go through `paths.mask_uri()` (scheme / host /
  database only):

  ```python
  from paths import mask_uri
  print(f"[mock] MongoDB unreachable（{mask_uri(MONGO_URI)}), returning mock data.")
  # mongodb+srv://***:***@cluster0.xxx.mongodb.net/?retryWrites=true
  ```

- the Streamlit page runs every child-process output through `paths.mask_secrets()` (connection strings,
  `sk-` keys, `Bearer` tokens, `key=value`) because the page is **public**;
- if a real-looking key ever appears in the repository, rotate it immediately.

---

## Post-mortems (20)

From sandbox restrictions and model code hallucination to charset conflicts, vector-space clashes,
fallback drills and MCP protocol-wire pollution — the full write-up plus 44 screenshots is in
**[docs/PITFALLS.md](docs/PITFALLS.md)**.

---

## Roadmap

- [ ] **Upgrade the retrieval fallback to vector level**: today it degrades to keyword recall (zero deps
      but weaker than vectors); next is local-embedding or cached-vector fallback
- [ ] Complete the resilience chain: exponential backoff + jitter + circuit breaker + time budget + idempotent `request_id`
- [ ] RAG evaluation set and metrics: `hit@k` / `MRR` / answer accuracy / token cost as a single-command report
- [ ] Wire the multi-agent module to a real vector store and an LLM reviewer (round-1 vs round-2 recall lift)
- [ ] MCP probe: assert control frames (`initialized` / `ping` / `progress` / `cancellation`)
- [ ] Optional full-dependency CI job (runs the MCP end-to-end negative case)
- [ ] `docker-compose.yml` (app + ollama) so the fallback chain works inside containers
- [ ] Keep `README_EN.md` in sync with the Chinese version (synced once so far)

---

## License

[MIT](LICENSE) © 2026 Rundong Yang
