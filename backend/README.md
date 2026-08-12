# ApplyPilot 后端

后端使用 FastAPI、SQLModel、Alembic 和 PostgreSQL，负责认证、个人档案、项目证据、申请任务及 Agent 执行。

## 本地启动

先在项目根目录复制并填写 `.env.example`，然后运行：

```bash
uv sync
cd backend
uv run alembic upgrade head
uv run python -m app.initial_data
uv run python -m app.seed_programs
uv run fastapi dev app/main.py
```

API 地址为 <http://localhost:8000/api/v1>，接口文档为 <http://localhost:8000/docs>。

## 测试

```bash
uv run pytest tests -q
```

真实模型测试需要有效的 `AGENT_BASE_URL`、`AGENT_API_KEY` 和 `AGENT_MODEL`。没有模型密钥时，可按根 README 中的命令只运行确定性测试。

## 数据库迁移

修改 SQLModel 表结构后创建并执行迁移：

```bash
uv run alembic revision --autogenerate -m "说明本次修改"
uv run alembic upgrade head
```

已有迁移属于数据库历史，不能随意删除、改名或调整 revision 关系。
