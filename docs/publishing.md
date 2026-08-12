# 发布到 GitHub

该目录尚未初始化为独立 Git 仓库。发布前在项目根目录执行：

```powershell
git init
git branch -M main
git add .
git status --short
git diff --cached --check
```

我会在提交前重点检查以下内容：

- 不应出现 `.env`、`.venv`、`.venv-python314-backup`、`.idea` 或缓存目录；
- 应出现 `.env.example`，且其中只能有占位值；
- 应包含 `reports/2026-08-12/` 和对应的 `data/runs/2026-08-12/manifests/`；
- 文档链接应为仓库内相对路径，不包含本机绝对路径。

确认后再提交并推送：

```powershell
git commit -m "feat: build auditable daily AI insight pipeline"
git remote add origin 你的GitHub仓库地址
git push -u origin main
```

如果远端已经配置，先用 `git remote -v` 检查，不重复添加。任何时候如果 `.env` 出现在待提交列表中，都应停止提交并先修正忽略规则；密钥一旦进入 Git 历史，仅补充 `.gitignore` 并不能消除泄露风险。
