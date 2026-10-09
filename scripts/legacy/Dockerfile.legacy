# ---------------------------------------------------------------------------
# Dockerfile — My-Agent-Debugger
#
# 项目唯一的第三方依赖是 pymongo（见 requirements.txt）；其余导入均为 Python
# 标准库。因此依赖层很薄，把 requirements.txt 单独提前 COPY 能让 pip 层长期
# 命中缓存：只要依赖没变，改业务代码就不会重新装包。
#
# 构建：
#     docker build -t my-agent-debugger .
#
# 运行（需要 MongoDB 与 API Key，通过环境变量传入，不写进镜像）：
#     docker run --rm \
#       -e MONGO_URI="mongodb://host.docker.internal:27017/" \
#       -e DEEPSEEK_API_KEY="sk-xxxx" \
#       my-agent-debugger
# ---------------------------------------------------------------------------

FROM python:3.11-slim

# 让容器内的 Python 不再复现 README 案例 3 的乱码问题：
# 容器里 stdout 是管道而非 TTY，若按 C locale 编码输出就会出现 mojibake，
# PYTHONIOENCODING=utf-8 让父子进程编码对齐（router.py 第 91 行也做了同样的注入，
# 这里在镜像层再兜一层，避免依赖调用方是否传参）。
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1

LABEL description="My-Agent-Debugger: multi-model routing + hybrid generation/execution workflow demo"

WORKDIR /app

# --- 依赖层（缓存友好）-----------------------------------------------------
# 只拷贝 requirements.txt：此层仅在依赖变更时失效。
COPY requirements.txt /app/

# --no-cache-dir 避免把 pip 下载缓存留在镜像里，保持 slim 体积。
# 使用清华镜像源加速国内构建。
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

# --- 代码层 ---------------------------------------------------------------
# 依赖装完后再拷贝其余文件：改代码只会让这一层失效，不会重装依赖。
COPY . .

# 默认入口：无参数时执行一次学生查询演示（router.py 会解析出 id=2）。
CMD ["python", "router.py", "帮我查学生2"]
