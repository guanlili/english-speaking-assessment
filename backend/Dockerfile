FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

# 国内优先镜像；索引过期/不可用时恢复基础镜像的官方源，不关闭有效期校验。
# 音频转码：浏览器 webm/opus → 方舟支持的 wav。
RUN set -eu; \
    sources=/etc/apt/sources.list.d/debian.sources; \
    if [ ! -f "$sources" ]; then sources=/etc/apt/sources.list; fi; \
    cp "$sources" /tmp/debian.sources.original; \
    sed -i 's|deb.debian.org|mirrors.tencent.com|g' "$sources"; \
    if ! (apt-get update -o APT::Update::Error-Mode=any && \
        apt-get install -y --no-install-recommends ffmpeg); then \
        cp /tmp/debian.sources.original "$sources"; \
        rm -rf /var/lib/apt/lists/*; \
        apt-get update -o APT::Update::Error-Mode=any; \
        apt-get install -y --no-install-recommends ffmpeg; \
    fi; \
    rm -f /tmp/debian.sources.original; \
    rm -rf /var/lib/apt/lists/*

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

# 索引配置只对非 --frozen 解析生效；--frozen 安装按 lock 内锁定的 URL 下载，
# 镜像加速由下方构建时的 lock URL 改写实现（见 Install dependencies 段注释）。
ARG UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
# uv --frozen 只认 lock 里锁定的官方源 URL，服务器本地冷构建在跨境晚高峰会被
# 限速到 KB/s 级拖垮部署（2026-10-28 PR#202 事故根因）。构建时把下载 URL 前缀
# 改写到腾讯镜像：两者 /packages/ 路径同构、文件 sha256 相同，uv 哈希校验照常
# 生效；git 内的 lock 保持官方源不动，CI 海外 runner 校验/安装不受影响。
# 绑定挂载只读，因此 sed 到同目录新文件让 uv 读取改写副本。
# ⚠️ --mount=type=cache 是冷构建的防火墙（轮子焐在缓存里就无需下载），
# 任何情况下不得 docker buildx prune exec cachemount。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock.src \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    sed 's|https://files.pythonhosted.org/packages/|https://mirrors.cloud.tencent.com/pypi/packages/|g' uv.lock.src > uv.lock \
    && uv sync --frozen --no-install-workspace --no-dev --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
# lock URL 镜像改写与缓存纪律同上（Install dependencies 段注释）。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock.src \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    sed 's|https://files.pythonhosted.org/packages/|https://mirrors.cloud.tencent.com/pypi/packages/|g' uv.lock.src > uv.lock \
    && uv sync --frozen --no-dev --package app

WORKDIR /app/backend/

CMD ["sh", "-c", "fastapi run --workers ${WORKERS:-1}"]
