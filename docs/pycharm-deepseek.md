# 在 PyCharm 中配置 DeepSeek

在 PyCharm 中选择“打开”，然后选择项目根目录 `daily-ai-insight-engine`。

选择项目内的解释器：

```text
.venv\Scripts\python.exe
```

在项目根目录 `.env` 中填写：

```dotenv
MODEL_NAME=deepseek:deepseek-chat
DEEPSEEK_API_KEY=在这里粘贴你的真实密钥
```

`.env` 已被 Git 忽略。不要把实际密钥粘贴到聊天、README、源码或 Git 提交中。

在 PyCharm 底部 Terminal 中运行完整真实流程：

```powershell
.\.venv\Scripts\python.exe -m daily_ai_insight.cli run-live `
  --input data\input\2026-08-12.json `
  --merge-specs data\decisions\2026-08-12.event-merges.json `
  --report-date 2026-08-12 `
  --project-root .
```

运行后优先打开：

```text
reports\2026-08-12\report.html
```

如果上次已经有成功项，命令会自动续跑；只有确实希望全部重新调用模型时才加 `--fresh`。
