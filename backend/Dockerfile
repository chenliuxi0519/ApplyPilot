FROM oven/bun:1 AS frontend-build

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

ARG VITE_API_URL=

RUN bun run build


FROM python:3.14

ENV PYTHONUNBUFFERED=1

# 从官方镜像复制 uv，避免在构建时执行安装脚本。
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# 安装依赖时预编译字节码，并用复制方式处理缓存文件。
ENV UV_COMPILE_BYTECODE=1

ENV UV_LINK_MODE=copy

WORKDIR /app/

# 优先使用项目虚拟环境中的命令。
ENV PATH="/app/.venv/bin:$PATH"

# 先安装锁定依赖，提高业务代码变更后的构建复用率。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --package applypilot-backend

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

COPY --from=frontend-build /app/backend/app/frontend /app/backend/app/frontend

# 复制业务代码后安装 ApplyPilot 后端包。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --package applypilot-backend

WORKDIR /app/backend/

CMD ["fastapi", "run", "--workers", "4"]
