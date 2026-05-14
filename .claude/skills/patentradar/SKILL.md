---
name: patentradar
description: 专利侵权竞品分析 skill。输入专利公开号（如 CN114512759B / US10000000B2），输出可人工复核的 markdown 竞品分析报告。流程：拆解权利要求 → 搜索市场竞品 → 抓证据（含图像）→ 全部权利要求逐特征对比 → 生成报告。触发词：专利侵权分析、专利竞品、claim chart、专利公开号、CN/US/EP/JP 专利号、专利对比、技术特征对比、专利保护范围核查、侵权风险评估。不适用：专利申请文书撰写、专利无效宣告、知识产权法律咨询、专利诉讼策略。
---

# PatentRadar 专利侵权竞品分析

## 何时使用
用户给出**专利公开号**（CN/US/EP/JP 等格式）并要求做竞品分析 / 侵权风险评估 / claim chart 对比时触发。典型输入：

- `分析 CN114512759B 的市场竞品`
- `帮我跑下 US10000000B2 的侵权风险`
- `对比这个专利和现有产品：[公开号]`
- `专利 CN117584868B 的 TOP 5 竞品报告`

## 你需要的能力
- **Web 搜索**（多语言 query 拼接）
- **网页抓取**（HTML 解析 + PDF 阅读）
- **Vision**（识别产品图/规格表/拆解图）

## 工作流（4 模块串行，严格按顺序执行）

每个模块都有现成的 system prompt 文件，**必读**——按对应 prompt 输出严格符合 JSON schema 的结构化数据，下一模块复用上一模块输出。

| 模块 | 现成 prompt 文件 |
|---|---|
| 一 拆解 | [decompose.md](src/patentradar/llm/prompts/decompose.md) |
| 二 候选筛选 | [candidate_extract.md](src/patentradar/llm/prompts/candidate_extract.md) |
| 二 证据判定 | [evidence_extract.md](src/patentradar/llm/prompts/evidence_extract.md) |
| 三 全部权利要求 | [full_claim_chart.md](src/patentradar/llm/prompts/full_claim_chart.md) |
| 四 报告 overview | [report_overview.md](src/patentradar/llm/prompts/report_overview.md) |
| 四 报告 candidate | [report_candidate.md](src/patentradar/llm/prompts/report_candidate.md) |

JSON schema 在 [src/patentradar/schemas/](src/patentradar/schemas/)（Pydantic 模型，看字段名 + 校验规则即可）。

---

### 模块一：拆解权利要求

**输入**：专利公开号

**操作**：
1. 抓 `https://patents.google.com/patent/<PUB>/zh`（中国专利用 /zh，US 用 /en）
2. 抓全部权利要求原文（含从属权利要求）
3. 若 HTML 中出现图片/公式/乱码占位 → 抓官方 PDF 用 vision 还原（仅异常条款，正常条款用 HTML 原文）
4. 按 [decompose.md](src/patentradar/llm/prompts/decompose.md) 拆解每条权利要求为原子 feature

**关键规则**（详见 decompose.md）：
- 实质型独立权利要求的**主题前序作为首条 feature 单独保留**（如 `C1-F1: 一种车辆后备箱自动开启控制系统`），避免下游误判保护对象类型
- 公式 + 变量定义**合并为同一条 feature**（变量定义在公式前/后都属于该公式）
- 同部件的**列举 + 形状 + 位置 + 功能合并为一条**（"看 feature 引子是不是同一个部件名"判别）
- if-then-else 控制逻辑**整体保留**为一条，不要拆 then/else
- 引用条款（"应用于权利要求 X-Y..."）**剥离**，不作为 feature

**输出**：`task_package`（看 [schemas/task_package.py](src/patentradar/schemas/task_package.py)）
- `patent`: 公开号/标题/申请人/申请日/技术领域/Google Patents URL/PDF URL
- `claims`: 全部权利要求 + 各自 features 列表
- `claim_1_text` / `claim_1_features`: 单独提取权 1
- `technology_tag`: 技术领域标签（从 [configs/technology_tags.toml](configs/technology_tags.toml) 选）

---

### 模块二：竞品搜索 + 权 1 判定

模块二是 5 步流水线（在本 skill 里**合并为 3 个 LLM 阶段**——你有 web 搜索能力，不需要分 step1 query plan + step2 batch search）：

#### 阶段 2A：搜索 + 候选筛选

按 [candidate_extract.md](src/patentradar/llm/prompts/candidate_extract.md) 的规则：

1. **拼搜索 query**：基于 patent.title + claim_1 关键词 + 技术领域，多语言（中/英；JP 专利加日文）拼 8-15 条 query
2. **执行搜索**：在你的 web 搜索工具里跑
3. **过滤申请人自家产品**：跳过任何疑似申请人（patent.applicants）官网域名/子品牌
4. **筛 8-12 个候选**：每个候选必须细到具体型号 + 规格（如 "蜂巢能源 L600 196Ah 短刀片" 不能写"蜂巢能源短刀电池"）

**候选去重 key**：`(company, product_name)` 二元组——同公司多型号都要保留，但 `(同公司, 同产品名)` 重复算冲突。`product_version` 字段是**自然语言产品介绍**（1-2 句关键参数），不参与去重。

**权 1 明显不满足的直接丢弃**（如权 1 限定方壳，候选是圆柱）。

输出：候选列表（每个含 candidate_id `P01..PNN`、company / company_en / product_name / product_name_en / product_version / market / source_urls / initial_evidence_summary 等）。

#### 阶段 2B：单候选证据判定（每个候选两轮 LLM 调用）

按 [evidence_extract.md](src/patentradar/llm/prompts/evidence_extract.md)：

**Round 1（text-only，不看图）**：
- 抓每个候选的 source_urls + 跑 6-10 条初始搜索 query 抓 page 文本
- 按权 1 各 feature 给出 status ∈ {明确满足 / 可能满足 / 证据不足 / 明确不满足}
- 对 status ∈ {证据不足, 可能满足} 的 feature 列 1-3 条**具体的** `suggested_followup_queries`（含产品型号 + 想验证的维度，**绝不空泛**）

**Gap search**：用 LLM 给的 query 跑搜索 + 抓新 page + 抓图

**Round 2（看图）**：
- 合并 round 1 + gap 的所有证据
- 对每个候选只看 ≤5 张图（产品规格图/拆解图/尺寸图优先）
- 给最终判定，**清空** `suggested_followup_queries`

**评分规则**（严格执行，不得自我宽松）：
| status | ratio | 触发条件 |
|---|---|---|
| 明确满足 | 1.0 | 公开 URL 直接字面/数值证据，≥ 1 独立 host |
| 可能满足 | 0.8 | 公开证据严谨推理（必须给推理链） |
| 证据不足 | 0.3 | 证据池里找不到相关线索 |
| 明确不满足 | 0.0 | 公开证据直接矛盾（整候选 disqualified=true）|

`total_score = mean(各 feature ratio) × 100`；任一"明确不满足" → 整候选 disqualified=true, total_score=0。

**数学约束类特征必须现场算到具体数值**（D/V、S/E、L/S 等），写在 `competitor_feature` 字段，禁止只写"满足公式约束"。

#### 阶段 2C：排名 + 同公司去重

按 [scorer.py](src/patentradar/modules/competitor_search/scorer.py) 逻辑：
1. 过滤 disqualified
2. 按 `(total_score, evidence URL 数, candidate_id)` 降序
3. **同公司只保留最高分产品**（dedup by `company.lower().strip()`）
4. 截断到 TOP 5（或不足 5 个就全留）

**输出**：`TopCompetitorReport`（top_competitors + excluded_candidates）。

---

### 模块三：扩展到全部权利要求

按 [full_claim_chart.md](src/patentradar/llm/prompts/full_claim_chart.md)：

**对每个 TOP 候选跑两轮**：

**Round 1（text-only）**：
- 复用模块二的 evidence_pool（URL 列表 + 文本）
- 评估全部权利要求各 feature（不只权 1）
- 模块二已判 1.0 的权 1 特征**沿用判定 + 同 URL**
- 对 status ∈ {可能满足, 证据不足} 的特征列 `suggested_followup_queries`：
  - **权 1 缺口**每条 3-5 条 query（重要，挥霍预算）
  - **非权 1 缺口**每条 1-2 条 query
  - 单候选 query 总数硬上限 30 条
- **不要重复模块二跑过的 query**（评估前先扫一眼 `queries_already_tried_in_module_two`）

**Gap search**：跑 round 1 的 query → 抓新 page + 图

**Round 2（看图，看 ≤5 张图）**：
- 终判，`suggested_followup_queries` 必须为空
- **对权 1 中 status ∈ {可能满足, 证据不足} 的 feature 必填 `evidence_gap_brief`**（两行结构）：
  ```
  还缺：<具体技术维度，写清"已有证据为何不足以证明本特征，还缺 XXX 才能证明该特征">
  下一步建议：<明确去哪里（具体网站名如畅易汽车网、汽车之家、汽修巴巴、Google Patents 等真实网站）找什么，不要给 query 字串，给方向>
  ```
  - 不写"搜 XXX"这种 query 字串
  - 带 URL 必须是真实网站根域名，不能瞎编具体文章路径
  - 明确满足/明确不满足/非权 1/Round 1 一律 `evidence_gap_brief=""`

**评分规则**：
- `claim_score = mean(该 claim 各 feature.score) × 100`，任一"明确不满足" claim 直接 0
- **`total_score` 只看权 1**：`total_score = claim_1_score`
- 非权 1 不进 ranking，但 `claim_score` 留在每个 ClaimChartEntry 供报告展示
- **失格只看权 1**：仅权 1 任一特征"明确不满足"或 launch_date 早于专利申请日才 disqualified=true

**Round 1 disqualified 直接 short-circuit 跳 round 2**。

**输出**：`FullClaimChartReport`（top_competitors + excluded_candidates，每个含全部权利要求逐特征对比）。

---

### 模块四：生成 markdown 报告

模块四**拆成 N+1 次 LLM 调用**（避免单次响应过长触发 SSE 超时）：

#### 4A：Overview（1 次 LLM 调用）
按 [report_overview.md](src/patentradar/llm/prompts/report_overview.md)，生成报告第 1+2 章节：

- **第 1 章节 专利详细信息**：表格（公开号/标题/申请人/发明人/申请日/技术领域/Google Patents URL/官方 PDF URL）。**不展示权 1 原文**。
- **第 2 章节 整体侵权风险评估**：自然语言段落（不分小标题）覆盖：
  1. 疑似竞品概览（1 句，N 个候选 K 个进 TOP）
  2. 最高分竞品介绍（2-4 句）
  3. 最高分竞品的权 1 满足情况（1 段）
  4. **针对权 1 证据缺口的下一步搜索建议**：每条缺口 feature 1 条 bullet，**直接复用** `evidence_gap_brief` 字段（不要二次加工，不要造 query）
  5. 失格候选简述（若有）

#### 4B：Per-candidate 子节（每个 TOP 候选 1 次 LLM 调用）
按 [report_candidate.md](src/patentradar/llm/prompts/report_candidate.md)，每个候选独立生成：

- TOP{rank} 标题 + 元信息表（**无权 1 分数列，无深挖理由列**）
- 逐权利要求对比子小节（**不展示 claim_score**）：feature_id / 权利要求技术特征 / 竞品对应特征 / 状态 / 证据 URL（最多 5 个）/ 说明（reasoning ≤ 200 字）
- 该候选的证据缺口（只针对权 1）：**直接复用 evidence_gap_brief 字段**

#### 4C：相似专利核查（仅当 max_total_score ≥ 80）
按 [similar_patents.py](src/patentradar/modules/report/similar_patents.py) 构造 Google Patents 高级检索深链接（同国家 + 同申请人 + 同标题）—— 静态拼接，**不需要 LLM**。

#### 4D：拼接
- 第 1+2 章节（4A 输出）
- 第 3 章节标题：`## 3. TOP{N} 竞品深度对比`（动态 N，**不要硬写 TOP5**；6 个就写 TOP6，1 个就写 TOP1）
- 第 3 章节内容：所有 4B 输出按 rank 顺序拼接
- 第 4 章节（4C 输出，仅触发时）

**输出**：完整 markdown 报告（约 100-200KB），可选 WeasyPrint 渲染为 PDF。

---

## 关键约束（写错就重做）

| ❌ 不要 | ✅ 要 |
|---|---|
| 模块一里把"一种 XX"前序删掉 | 把"一种 XX"作为首条 feature `C1-F1` 单独保留 |
| 候选 dedup 用 `(company, product_name, product_version)` 三元组 | 只用 `(company, product_name)` 二元组 |
| TOP-N 排序后同公司多产品都进 | 同公司只保留最高分产品 |
| 报告里展示权 1 原文 | 第 1 章节不展示，只表格元信息 |
| 报告里展示 claim_score / 权 1 分数列 / 深挖理由 | 全删 |
| 模块四 LLM 自己临场造 query 字串 | 直接复用 `evidence_gap_brief`（已是格式化的"还缺 / 下一步建议"两行） |
| 单次 LLM 调用塞 6 候选完整数据 | 拆 1 overview + N per-candidate，每次只看 1 候选 |
| 数学约束类只写"满足公式约束" | 现场算出具体数值（如 `S=2(LH+LD+HD)=2×(574×118+574×21.5+118×21.5)=165220mm²`） |
| 报告搜索建议写"搜 XXX query" | 给方向（"去畅易汽车网定位 XX 维修手册的电路图章节"）|
| 评分时把"看到产品名但没参数"判可能满足 | 判证据不足 |

## 触发执行

用户给出公开号后：
1. **先确认**：扫一眼 `tests/decompose/outputs/<PUB>/task_package.json` 是否已存在
   - 在 → 询问用户是用 cache 还是重跑模块一
   - 不在 → 直接跑模块一
2. **按 4 模块顺序执行**，每模块跑完落盘 JSON（schema 在 `src/patentradar/schemas/`）便于审计
3. **每个候选独立隔离**：单候选 LLM/网络失败不要拖死整 pipeline，写一条 disqualified 占位继续
4. **失格候选要保留**到 `excluded_candidates`，不要直接丢弃
5. **最终交付物**：`<output_dir>/module_four/report.md`（可选 report.pdf）

## 输出位置约定

建议输出目录结构（参考现有 cross_llm_eval/ 产物）：
```
<output_dir>/
├── module_one/task_package.json          # 模块一
├── module_two/
│   ├── step3_candidate_shortlist.json    # 候选列表
│   ├── step4_candidates/P01.json, ...    # 每候选独立 cache
│   ├── step5_top5_claim1_candidates.json # TOP-N 报告
│   ├── visual_log_fetched/<cid>/         # fetcher 抓的全集图
│   └── visual_log_sent/<cid>/            # LLM 实际看到的图（≤5 张）
├── module_three/
│   ├── candidates/P01_round1.json, P01_round2.json, ...
│   ├── top5_full_claim_chart.json
│   ├── visual_log_fetched/<cid>/
│   └── visual_log_sent/<cid>/
└── module_four/
    ├── report.md
    └── report.pdf
```

## 参考实测样例

- [CN114512759B（蜂巢 L600 短刀，total=100）](tests/cross_llm_eval/CN114512759B/)
- [CN117584868B（车载显示终端旋转执行机构，max=53）](tests/cross_llm_eval/CN117584868B/codex_fresh/)
- [CN110316092B（HiPhi 中控屏滑动机构）](tests/cross_llm_eval/CN110316092B/)
- [CN105335144B（一数科技 AR 智能尾门）](tests/cross_llm_eval/CN105335144B/)

每个目录都有完整的 module_one → module_four 产物可供模仿格式。
