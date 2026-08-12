# Daily AI Insight Engine

这个项目解决的不是“让模型总结一批新闻”，而是一个更具体的工程问题：如何把来源混杂、粒度不同的近期 AI 信息，转成可验证、可追溯、失败后可恢复的日报生产链。

我把可核验性放在覆盖规模之前：先固定一组经过人工核对的近期来源，再让 DeepSeek 做有边界的语义抽取与事件分析；事实验证、事件排序、来源映射和最终验收则交给确定性代码。当前版本使用 16 条中英文信息，输出 JSON、Markdown、HTML 和 SVG 图表，并保留完整运行记录。

> 核心说明请先阅读：[项目说明文档](docs/project-overview.md)。其中集中说明了数据源、Schema、系统设计、AI 使用方式、Prompt、错误处理和完整流程。

## 当前运行快照

当前仓库只保留一套真实在线业务数据和报告：

| 指标 | 结果 |
|---|---:|
| 近期 AI 来源 | 16 条 |
| 语言 | 13 条英文、3 条中文 |
| 来源类型 | 4 类 |
| 有效结构化洞察 | 16 / 16 |
| 独立事件 | 15 个 |
| Top 事件 | 5 个 |
| 趋势 | 技术、应用、政策、资本 |
| 图表 | 3 张 SVG |
| 隔离记录 | 0 条 |
| 最终质量门 | 8 / 8 通过 |
| 在线模型请求 | 20 次 |

## 最终成品

- [HTML 可视化日报](reports/2026-08-12/report.html)
- [Markdown 日报](reports/2026-08-12/report.md)
- [结构化日报 JSON](reports/2026-08-12/report.json)
- [逐条结构化洞察](data/processed/2026-08-12/insights.jsonl)
- [事件聚合结果](data/processed/2026-08-12/events.jsonl)
- [完整运行清单](data/runs/2026-08-12/manifests/run.json)
- [最终验收记录](data/runs/2026-08-12/manifests/verify.json)

## 我做的关键取舍

| 决策 | 选择依据 | 接受的代价 |
|---|---|---|
| 人工核验来源，不先做通用爬虫 | 小规模日报中，发布日期、来源身份和正文质量比抓取数量更影响后续分析 | 采集还不能无人值守 |
| 抽取阶段 `batch_size=1` | 便于逐条校验证据、保存检查点、精确重试并隔离失败 | 请求次数更多，但本次估算额外缓存成本不到 ¥0.01 |
| 用事件聚合替代文章直接排名 | 同一发布可能有多篇报道，文章排名会重复占用读者注意力 | 需要维护人工复核的合并决策 |
| 重要度由代码计算 | 排名需要稳定、可解释、可复现，不能随模型措辞波动 | 评分权重需要后续用读者反馈校准 |
| 报告模型只读取已验证事件摘要 | 限制上下文范围，减少事实漂移，并保留 `fact_id` 追溯链 | 模型无法利用未被抽取出的长文细节 |
| 暂不引入数据库、向量库和 Web 服务 | 当前瓶颈是数据质量与分析可信度，不是存储规模或在线并发 | 还不具备生产调度和多人协作能力 |

## 系统如何工作

```text
人工检索并核验近期来源
  → Schema 校验、规范化、内容哈希、去重
  → DeepSeek 逐条抽取事件、实体、事实证据和影响
  → Schema、逐字证据、中文和置信度验证
  → 检查点 / 有限重试 / 失败隔离
  → 人工复核同事件合并关系
  → 程序确定性排名并选出 Top 5
  → DeepSeek 读取事件摘要生成中文报告分析
  → 来源 ID 映射
  → JSON / Markdown / HTML / SVG
  → 最终质量门
```

模型不会一次看到完整原始数据集。第一阶段每次只处理一条新闻；第二阶段只读取验证后的事件摘要、证据事实、影响评分、重要度和 ID，不读取整批原始文章。这是我为证据归属、精确重试和上下文约束做出的实现选择，而不是流程本身的先验限制。

## 结构化抽取

项目不只生成摘要，而是使用版本化 Pydantic Schema 抽取：

- 事件类型与主题；
- 组织、人物、产品、模型、技术、地点和法规实体；
- 带 `fact_id` 和逐字 `evidence` 的关键事实；
- 目标级情绪及置信度；
- 技术、应用、政策、资本四维影响；
- 必须引用事实 ID 的风险与机会；
- 模型名称、Prompt 版本、抽取时间和 Schema 版本。

同一现实事件的多篇报道会进入 `EventCluster`，日报对事件排名而不是对文章排名。完整设计见[项目说明文档](docs/project-overview.md#3-结构化数据模型)。

## Harness Engineering

项目采用开源 [Pydantic AI](https://github.com/pydantic/pydantic-ai) 加仓库内轻量 Harness：

- `AGENTS.md`：工程约束和完成标准；
- `prompts/extract_v2.md`：逐条结构化抽取 Prompt；
- `prompts/report_v3.md`：带事实 ID 引用的事件级报告 Prompt；
- `prompts/report_v2.md`：保留的上一版报告 Prompt，便于版本审计；
- `skills/extract-news-insight/SKILL.md`：实际注入抽取 Agent 的领域 Skill；
- `src/daily_ai_insight/harness/`：证据、中文、引用和生命周期 Hooks；
- `data/runs/2026-08-12/`：真实消息、Trace、Token、尝试历史和产物哈希。

Schema、证据或中文质量不合格时，Agent 最多自动修复 2 次；仍失败或置信度低于 0.60 时进入隔离区。续跑必须同时匹配输入哈希、模型、Prompt 和 Schema 版本。

## 快速开始

### 1. 打开项目

打开项目根目录 `daily-ai-insight-engine`，Python 版本要求为 3.11 或更高。

### 2. 创建环境并安装依赖

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[ai,report,dev]"
```

如果 `.venv` 已经存在，只需执行安装命令。

### 3. 配置 DeepSeek

在项目根目录创建或修改 `.env`：

```dotenv
MODEL_NAME=deepseek:deepseek-chat
DEEPSEEK_API_KEY=你的真实密钥
```

`.env` 已被 Git 忽略。不要把真实密钥写入 README、源码、截图或 Git 提交。

### 4. 一键运行

```powershell
.\.venv\Scripts\python.exe -m daily_ai_insight.cli run-live `
  --input data\input\2026-08-12.json `
  --merge-specs data\decisions\2026-08-12.event-merges.json `
  --report-date 2026-08-12 `
  --project-root .
```

默认采用安全续跑：已经成功且版本匹配的逐条洞察不会重复调用。只有明确需要清空该日期产物并重新调用模型时才添加 `--fresh`。

## 项目结构

```text
daily-ai-insight-engine/
├─ AGENTS.md                         工程约束与完成标准
├─ data/
│  ├─ input/                         人工核验输入
│  ├─ raw/                           规范化事实层
│  ├─ decisions/                     人工复核的事件合并决策
│  ├─ processed/2026-08-12/          洞察、事件和报告分析
│  └─ runs/2026-08-12/               消息、Trace、隔离与 Manifest
├─ docs/                              项目说明、设计、数据源与评测
├─ prompts/                           两阶段当前 Prompt 与报告 Prompt 历史
├─ reports/2026-08-12/               最终日报与图表
├─ skills/                            抽取 Agent 使用的 Skill
├─ src/daily_ai_insight/              业务实现
├─ templates/                         Markdown 与 HTML 模板
└─ tests/                             Schema、Harness 和端到端测试
```

## 说明文档

- [项目说明文档](docs/project-overview.md)：问题定义、关键决策、完整流程与运行复盘；
- [数据源说明](docs/data-sources.md)：来源、逐条选择理由和数据特点；
- [系统设计](docs/design.md)：数据合同、架构决策、评分和失败恢复；
- [Harness Engineering](docs/harness.md)：Agent 边界、Prompt、Hooks 和续跑机制；
- [质量标准](docs/quality-standards.md)：数据、证据、报告和运行质量门；
- [运行复盘](docs/evaluation.md)：真实运行指标、失败修复与测试覆盖；
- [成本与性能](docs/cost-and-performance.md)：Token、费用、延迟和批量权衡；
- [PyCharm 与 DeepSeek](docs/pycharm-deepseek.md)：本地配置说明；
- [发布前检查清单](docs/release-checklist.md)：数据、代码、文档和密钥自检；
- [GitHub 发布说明](docs/publishing.md)：独立仓库初始化和推送步骤。

## 质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pip check
```

当前结果为 24 项测试全部通过、Ruff 检查通过、依赖检查无冲突。端到端测试使用 Pydantic AI 测试替身，不联网，也不会生成第二套业务样本或报告。