# ApplyPilot

ApplyPilot 是一个面向中文用户的留学申请规划与管理平台。用户可以通过对话查找院校项目、比较申请要求、分析个人背景，并把选校结果整理成申请计划和材料任务。

这个项目不仅接入了大语言模型，还实现了工具调用、权限检查、人工确认、状态恢复和证据校验。模型负责理解用户需求和选择工具，真正的数据读写仍由后端服务完成。

## 主要功能

- 管理教育背景、GPA、语言成绩、经历、预算和申请方向
- 按地区、申请季和专业方向搜索硕士项目
- 对比最多三个项目，并查看学术、语言、学费和截止日期要求
- 根据个人档案给出冲刺、匹配和稳妥分类
- 创建申请计划，使用看板管理状态、材料和截止日期
- 通过 AI 对话读取档案、搜索项目、查询要求和管理申请任务
- 查看院校要求对应的官网来源、采集时间和验证状态
- 在修改关键资料或申请状态前请求用户确认
- 保存会话和运行记录，刷新页面后可以继续查看

目前项目库收录了新加坡、中国香港和英国的 7 所学校、11 个授课型硕士项目。

## 技术实现

- **Agent 编排**：使用 LangGraph StateGraph 组织模型调用、工具路由和结果返回。高风险操作通过 `interrupt()` 暂停，用户确认后使用 `Command(resume=...)` 继续执行。PostgresSaver 会加密保存运行状态，使等待确认的任务在后端重启后仍可恢复。

- **工具与权限**：模型只负责选择工具，实际操作由后端执行。所有工具都会经过 Pydantic 参数校验和权限判断，并复用 API 的领域服务和业务规则。用户身份来自登录状态，模型不能直接修改数据库或访问其他用户的数据。

- **上下文与记忆**：每次模型调用只组合当前需要的用户档案、长期偏好、申请状态、相关证据、历史摘要和最近消息。LangGraph Checkpoint 保存会话内的短期状态；跨会话的长期信息分为两类——有唯一真值、可校验的事实（GPA、语言成绩、申请状态）存在档案和申请表里，没有真值、只能由用户表态的偏好（校园环境、学校类型）存在独立的偏好表里。历史过长时会压缩较早内容，减少无关上下文和 Token 消耗。

- **偏好的版本与冲突**：模型写入偏好时必须声明这次是新增、细化还是推翻旧值，声明会与数据库中的实际存量核对，对不上会被拒绝并要求重新判断。推翻或撤销一条已生效的长期约束属于高风险操作，需要用户确认后才执行，用户拒绝时旧值原样保留。被覆盖和被撤销的记录不会删除，保留变更类型、用户原话和取代关系，可以回溯任意一条约束是何时、因为哪句话失效的。

- **迭代与回归**：评测结果可以导出 JSON 并作为下一次运行的基线。对照会逐用例列出修复和回归，只有在没有任何用例退步时才判定为改进；出现回归时退出码非零，可直接用于 CI 门禁。报告中记录 prompt 摘要和模型标识，用于区分是哪个变量导致了结果变化。

- **证据与评测**：院校要求保留官网来源、采集时间和原文片段。Evidence Verifier 会核对回答中的证据编号、网址、数值和申请季。项目还包含 Prompt Injection 测试和 57 条确定性 Agent 评测用例，覆盖工具执行、人工确认、错误恢复、证据校验和安全场景。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、Tailwind CSS、TanStack Router、TanStack Query |
| 后端 | FastAPI、SQLModel、Pydantic、Alembic |
| 数据库 | PostgreSQL |
| Agent | LangGraph、Anthropic Python SDK、Tool Calling、PostgresSaver |
| 部署 | Docker Compose |
| 测试 | pytest、Playwright、Ruff、mypy |

## 本地运行

开始前需要安装 Docker Desktop、Node.js 和 npm。

### 1. 配置环境变量

在项目根目录执行：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，至少修改以下配置：

```dotenv
SECRET_KEY=<随机字符串>
POSTGRES_PASSWORD=<数据库密码>
FIRST_SUPERUSER_PASSWORD=<管理员密码>
```

如需使用 AI 对话，还需要填写兼容 Anthropic Messages 协议的模型服务：

```dotenv
AGENT_BASE_URL=https://api.deepseek.com/anthropic
AGENT_API_KEY=<API Key>
AGENT_MODEL=deepseek-v4-flash
```

如需启用 LangGraph 和持久化状态，再加入：

```dotenv
AGENT_ENGINE=graph
CHECKPOINT_ENCRYPTION_KEY=<16、24 或 32 字节的密钥>
```

Checkpoint 会保存完整对话和工具结果，因此加密密钥应与 `SECRET_KEY` 分开管理。未配置该密钥时，本地环境不会写入 Checkpoint；非本地环境会直接拒绝启动。

### 2. 启动数据库和后端

```powershell
docker compose up -d db mailcatcher backend
```

首次启动会执行数据库迁移并创建初始管理员。配置了 Checkpoint 密钥时，也会初始化 LangGraph 使用的数据库表。

### 3. 导入院校项目数据

```powershell
docker compose exec backend python -m app.seed_gold_requirements
```

### 4. 启动前端

```powershell
npm install
npm run dev
```

启动完成后可以访问：

- 前端：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>
- 测试邮件：<http://localhost:1080>

## 运行测试

后端测试必须使用名称中包含 `test` 的独立数据库。测试结束时会清理该数据库中的业务表，不能连接开发数据库。

```powershell
cd backend
$env:POSTGRES_DB = "applypilot_test"
uv run alembic upgrade head
uv run pytest tests -q
```

运行后端静态检查：

```powershell
uv run ruff check app tests
uv run mypy app
```

运行前端构建检查：

```powershell
cd ..
npm run build --workspace frontend
```

运行确定性 Agent 评测：

```powershell
cd backend
uv run python -m app.evaluation.run --json eval_report.json
```

与上一次结果对照，出现回归时退出码非零：

```powershell
uv run python -m app.evaluation.run --baseline eval_report.json --json eval_next.json
```

运行真实模型评测：

```powershell
uv run python -m app.evaluation.run --mode real
```

真实模型评测需要有效的 `AGENT_API_KEY`，并会产生模型调用费用。

## 项目来源

ApplyPilot 基于 MIT 许可的 [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) 搭建基础结构。留学申请领域模型、证据系统、Agent 工作流、工具权限、人工确认、项目检索和申请看板等功能在此基础上完成。
