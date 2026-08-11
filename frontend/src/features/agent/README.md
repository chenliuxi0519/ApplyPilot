# Agent 页面边界

Agent 页面只负责展示对话、工具结果和确认操作，不在前端判断业务是否合法。

- 确认或拒绝会调用后端继续同一次 Agent 运行，前端不直接修改申请数据。
- 工作区每轮对话后重新读取业务 API，以数据库结果为准，不相信模型对执行结果的描述。
- 只有白名单中的工具结果可以渲染为结构化卡片，其他结果只显示安全的中文摘要，不展示原始参数。

对话式交互参考了 [assistant-ui](https://github.com/assistant-ui/assistant-ui) 和 [vercel/ai-chatbot](https://github.com/vercel/ai-chatbot) 的公开设计思路，但没有复制其代码，也没有引入它们作为依赖。
