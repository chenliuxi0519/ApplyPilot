# 参与开发

先看 [README](README.md) 把环境跑起来。

提 PR 之前跑一下：

```bash
cd backend && uv run pytest tests -q
npm run build --workspace frontend
```

改了接口记得重新生成前端客户端（`bash scripts/generate-client.sh`）。

## 几条项目规则

- 院校要求必须带官网链接和采集时间，不能拿模型说的当官方信息
- 改档案、提交申请这类操作要走人工确认，别绕过领域服务直接写库
- 别提交 `.env` 和任何密钥
- 界面文案用中文，代码里的标识符和第三方库名保持英文
- 注释只写代码本身看不出来的原因
