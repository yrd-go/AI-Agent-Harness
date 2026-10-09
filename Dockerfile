# ---------------------------------------------------------------------------
# Dockerfile —— my-agent Streamlit 控制台（重构后的目录结构）
#
# 说明：
#   - 主部署目标是 Streamlit Cloud（入口 streamlit_app.py），本文件仅供
#     自建服务器 / 内网离线环境使用，二者并不冲突。
#   - 依赖源自根目录 requirements.txt；安装层单独提前 COPY，改业务代码
#     不会触发重新装包。
#   - 所有资源路径都在运行期由 src/paths.py 动态解析，容器里的工作目录
#     固定为 /app（= 仓库根），因此与本地 Windows 行为一致。
#   - 迁移前的旧版 Dockerfile 已归档在 scripts/legacy/Dockerfile.legacy。
#
# 构建：
#     docker build -t my-agent-console .
#
# 运行（密钥通过环境变量注入，绝不写进镜像）：
#     docker run --rm -p 8501:8501 \
#       -e ZHIPU_API_KEY="sk-xxxx" \
#       -e MONGO_URI="mongodb://host.docker.internal:27017/" \
#       my-agent-console
#   然后浏览器打开 http://localhost:8501
# ---------------------------------------------------------------------------

FROM python:3.12-slim

# 容器内 stdout 不是 TTY，按 C locale 输出会导致中文乱码；
# 显式统一 UTF-8，并关闭字节码写入保持镜像干净。
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true

LABEL description="my-agent: RAG + multi-agent + router + MCP probe + function calling (Streamlit console)"

WORKDIR /app

# --- 依赖层（缓存友好）-----------------------------------------------------
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# --- 代码层 ---------------------------------------------------------------
# 代码、数据（data/）、配置（.streamlit/）、脚本（scripts/）都要进镜像；
# .env 与 secrets.toml 由 .dockerignore 排除，密钥只走环境变量。
COPY . /app

EXPOSE 8501

# 健康检查：容器起来后探测一次首页（失败只标记 unhealthy，不影响运行）
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

# 默认入口：Streamlit 控制台（与云端一致的入口文件）
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
