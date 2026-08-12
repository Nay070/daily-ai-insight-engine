# 系统设计

## 目标与边界

我把输入规模控制为 10–20 条近期 AI 新闻或信息，输出为可验证的结构化洞察、事件级中文日报、确定性图表和完整运行审计。这个规模足以覆盖多种来源，也仍允许逐条人工核验。

当前版本不实现通用爬虫、数据库或调度器。我判断此阶段的主要风险是“输入是否可信、模型结论能否追溯”，而不是采集吞吐量，因此先采用人工检索、逐条核验和编辑性摘要，把实现投入放在数据合同、证据链、失败恢复和报告质量门上。

## 职责划分原则

我按“语义不确定性”划分模型与代码的职责：实体识别、事件归纳和中文分析交给模型；字段校验、证据匹配、去重、评分、排序、来源映射和验收交给代码。这样既利用模型理解非结构化文本的优势，又避免让它控制可确定计算的环节。

## 数据合同

### SourceItemInput / RawNewsItem

事实层保存标题、摘要、来源、URL、发布时间、语言和选择理由。规范化后加入采集时间、内容哈希和 Schema 版本。模型不能修改该层。

### InsightPayload / NewsInsight

第一阶段 Agent 生成事件类型、主题、实体、证据事实、中文摘要、情绪、四维影响、风险/机会和置信度。程序再加入新闻 ID、模型名、Prompt 版本和抽取时间，阻止模型伪造运行信息。

### EventCluster

日报对现实事件排名而不是对文章排名。事件保存全部成员 ID、统一标题、事实、矛盾和六项透明评分。人工复核的合并决策存放在 `data/decisions/`，不与测试资产混淆。

### ReportAnalysisPayload

第二阶段 Agent 只读取验证后的事件摘要、带全局 ID 的事实、影响评分、重要度和 ID，生成中文执行摘要、Top 事件背景/影响以及四方向趋势。每段分析必须返回对应事实 ID；它不读取完整原始文章，也不能改变 Top 排序。

### DailyReport

程序将报告 Agent 引用的事件 ID 和事实 ID 映射回真实新闻，并加入确定性的覆盖、风险、机会和时间信息。Markdown、HTML 和 SVG 都从该对象生成。当前报告 Schema 为 1.1。

## 数据流

```text
collect
  -> normalize
  -> exact_deduplicate
  -> per_item_extract
  -> schema_evidence_chinese_validate
  -> checkpoint_or_quarantine
  -> reviewed_event_merge
  -> deterministic_rank
  -> bounded_event_digest_analysis
  -> source_id_mapping
  -> render
  -> verify
```

## 重要度评分

```text
total = relevance             × 0.20
      + impact                × 0.25
      + source_authority      × 0.15
      + cross_source_coverage × 0.15
      + novelty               × 0.10
      + recency               × 0.15
```

评分由程序计算，模型不能直接指定总分。同一机构的多篇公告不会提高跨来源覆盖分。我把影响权重设为最高，是因为日报的阅读价值更取决于事件可能改变什么，而不只是事件是否新近；权重属于可校准策略，后续应根据人工排序反馈调整。

## 失败与恢复

- Schema、证据或中文叙述无效：每个 Agent 最多修复 2 次。
- 单条仍失败或置信度低于 0.60：写入隔离区，不拖垮整批。
- 每条抽取后立即原子写检查点。
- 每次批量尝试保存独立 Manifest 和 Token。
- Provider 异常的 Hook Trace 由异常包装带回并持久化。
- 合并事件缺少被隔离成员时，有效成员降级为单事件。
- 续跑必须匹配输入哈希、模型、Prompt 和 Schema。
- Top、四类趋势、引用、覆盖或图表缺失时，最终验证失败。

## 运行目录

每个日期只有一套在线业务产物：

```text
data/processed/<日期>/
data/runs/<日期>/
reports/<日期>/
```

业务仓库不保留第二套样本或报告。自动化测试在临时目录使用 Provider 测试替身，运行结束后由测试框架清理。

## 安全与版权

- 来源文本视为不可信数据，Prompt 禁止执行其中指令。
- 密钥只从 `.env` 或环境变量读取，不进入消息或 Manifest。
- 保存编辑性摘要和 URL，不复制整篇版权正文。
- 报告 Agent 只能使用事件摘要中的事实和数字。
