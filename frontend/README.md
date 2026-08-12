# ApplyPilot 前端

前端使用 React、TypeScript、Vite、Tailwind CSS、TanStack Router 和 TanStack Query，所有用户页面均面向中文用户。

## 本地启动

在项目根目录运行：

```bash
npm install
npm run dev
```

开发地址为 <http://localhost:5173>。默认连接 <http://localhost:8000> 的后端；需要连接其他地址时设置 `VITE_API_URL`。

## 构建与测试

```bash
npm run build --workspace frontend
npm test
```

Playwright 测试需要后端和测试数据库可用。`npm run lint` 当前包含自动修复参数，运行前应确认工作区改动。

## 目录说明

- `src/features`：Agent、个人档案、项目、证据和申请页面。
- `src/components`：通用组件与基础 UI。
- `src/routes`：页面路由。
- `src/client`：根据 OpenAPI 自动生成的客户端，不手工修改。
- `tests`：Playwright 端到端测试。
