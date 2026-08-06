# top_competitors.json schema

模块二输出 → 模块三输入。

## 顶层结构

```json
{
  "publication_no": "CN114512759B",
  "top_competitors": [<CandidateEvidence>, ...],
  "excluded_candidates": [<CandidateEvidence>, ...]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `publication_no` | string | ✅ | 来自 task_package.patent.publication_no |
| `top_competitors` | CandidateEvidence[] | ✅ | TOP-N（≤ 5），按 total_score 降序，同公司去重 |
| `excluded_candidates` | CandidateEvidence[] | ✅ | 失效候选（disqualified=true），可为空 |

## CandidateEvidence 子结构

```json
{
  "candidate": {
    "candidate_id": "P01",
    "company": "蜂巢能源",
    "company_en": "SVOLT",
    "product_name": "L600短刀片磷酸铁锂电芯",
    "product_name_en": "L600 LFP blade cell",
    "product_intro": "第二代 3.2V 196Ah；21.5×574×118mm；627.2Wh",
    "market": "中国新能源动力/储能电池前装市场",
    "reason_for_deep_dive": "...",
    "source_result_ids": [],
    "source_urls": ["..."],
    "initial_evidence_summary": "..."
  },
  "launch_date": "2023 年 5 月下线交付",
  "launch_date_evidence": [
    {"url": "https://...", "title": "...", "source_name": "...", "snippet": "..."}
  ],
  "disqualified": false,
  "disqualification_reason": "",
  "comparisons": [<FeatureComparison>, ...],
  "total_score": 96.67,
  "searched_queries": ["..."],
  "searched_providers": []
}
```

### candidate 子字段
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `candidate_id` | string | ✅ | `P01..PNN` 格式 |
| `company` | string | ✅ | 公司中文名 |
| `company_en` | string | ✅ | 公司英文/品牌（必填，用于英文搜索）|
| `product_name` | string | ✅ | 产品中文名 |
| `product_name_en` | string | ✅ | 产品英文名（必填）|
| `product_intro` | string | ✅ | 产品介绍（1-2 句自然语言）|
| `market` | string | ✅ | 市场/应用场景描述 |
| `reason_for_deep_dive` | string | ✅ | 为什么值得深挖 |
| `source_result_ids` | string[] | ✅ | 搜索结果 id 列表（可空数组）|
| `source_urls` | string[] | ✅ | URL 列表 |
| `initial_evidence_summary` | string | ✅ | 关键证据摘要 |

### CandidateEvidence 顶层字段
| 字段 | 类型 | 说明 |
|---|---|---|
| `launch_date` | string | 中文+具体年月；找不到写"未明确" |
| `launch_date_evidence` | EvidenceSource[] | ≥ 1 个 URL（除非 launch_date="未明确"）|
| `disqualified` | bool | 整候选是否失效 |
| `disqualification_reason` | string | disqualified=true 时必填 |
| `comparisons` | FeatureComparison[] | 权 1 全部 feature 的判定 |
| `total_score` | number 0-100 | mean(各 feature score) × 100 |
| `searched_queries` | string[] | 该候选实际跑过的 query |
| `searched_providers` | string[] | 用过的搜索后端（可空数组）|

## FeatureComparison

```json
{
  "feature_id": "C1-F1",
  "patent_feature": "一种锂离子电池电芯",
  "competitor_feature": "蜂巢能源 L600 196Ah 短刀片是一种锂离子电池电芯（LFP 化学体系）",
  "status": "明确满足",
  "score": 1.0,
  "evidence": [
    {"url": "...", "title": "...", "source_name": "...", "snippet": "..."}
  ],
  "reasoning": "...",
  "suggested_followup_queries": [],
  "evidence_gap_brief": ""
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `feature_id` | string | 格式 `C\d+-F\d+`，对应 task_package 中的 feature_id |
| `patent_feature` | string | 权利要求 feature 原文 |
| `competitor_feature` | string | 候选对应表述（数学约束类必须含计算式 + 数值）|
| `status` | enum | `明确满足` / `可能满足` / `证据不足` / `明确不满足` |
| `score` | number | 严格按 status 派生：1.0 / 0.8 / 0.3 / 0.0 |
| `evidence` | EvidenceSource[] | 证据 URL 列表（图证据 url 写页面 URL，snippet 加 "图示证据：" 前缀）|
| `reasoning` | string | ≤ 200 字，必须给推理链 + 数值（数学约束类）|
| `suggested_followup_queries` | string[] | 模块二最终输出留空数组（已搜完）|
| `evidence_gap_brief` | string | 模块二阶段一律留空字符串（模块三才填）|

## EvidenceSource

```json
{
  "url": "https://...",
  "title": "页面标题",
  "source_name": "evlithium",
  "snippet": "Dimensions 21.5×574×118mm, Energy ≥625Wh"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `url` | string | 必须是绝对 URL（http:// 或 https://）|
| `title` | string | 页面标题（可空）|
| `source_name` | string | 来源站点缩写（可空）|
| `snippet` | string | 关键证据摘录（图证据用 "图示证据：xxx" 前缀）|

## 关键约束
- `top_competitors` 每家公司唯一（按 `company.lower().strip()` 去重）
- `top_competitors` 长度 ≤ 5
- 失效的候选放进 `excluded_candidates`，不要放进 `top_competitors`
- 任一 feature `status="明确不满足"` → `disqualified=true, total_score=0`
- "明确满足" 必须 ≥ 1 个独立 host 的 evidence URL
