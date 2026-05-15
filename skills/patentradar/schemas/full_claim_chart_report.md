# full_claim_chart.json schema

模块三输出 → 模块四输入。

## 顶层结构

```json
{
  "publication_no": "CN114512759B",
  "top_competitors": [<FullClaimChartCandidate>, ...],
  "excluded_candidates": [<FullClaimChartCandidate>, ...]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `publication_no` | string | ✅ | 同模块二 |
| `top_competitors` | FullClaimChartCandidate[] | ✅ | 通过模块三补搜后非失格的候选 |
| `excluded_candidates` | FullClaimChartCandidate[] | ✅ | 模块二就失格或模块三新发现失格的候选 |

## FullClaimChartCandidate

```json
{
  "candidate": {<同模块二 candidate>},
  "launch_date": "...",
  "launch_date_evidence": [...],
  "disqualified": false,
  "disqualification_reason": "",
  "claim_charts": [<ClaimChartEntry>, ...],
  "claim_1_score": 90.0,
  "total_score": 90.0,
  "searched_queries": [...],
  "searched_providers": []
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `candidate` | object | 同模块二 CandidateEvidence.candidate（结构完全一致）|
| `launch_date` / `launch_date_evidence` | — | 同模块二，模块三复用；若新拿到证据证明早于申请日则更新为 disqualified |
| `disqualified` / `disqualification_reason` | — | 同模块二，仅"权 1 任一明确不满足"或"launch_date 早于专利申请日"触发 |
| `claim_charts` | ClaimChartEntry[] | **全部权利要求**的对比（按 claim_no 1, 2, 3, ... 顺序）|
| `claim_1_score` | number 0-100 | 权 1 总分（= claim_charts[claim_no==1].claim_score）|
| `total_score` | number 0-100 | **只看权 1**：total_score = claim_1_score |
| `searched_queries` | string[] | 模块三跑过的 query（不包括模块二的）|
| `searched_providers` | string[] | 用过的搜索后端 |

## ClaimChartEntry

```json
{
  "claim_no": 1,
  "claim_text": "1.一种锂离子电池电芯...",
  "comparisons": [<FeatureComparison>, ...],
  "claim_score": 90.0
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `claim_no` | int | 权利要求编号，与 task_package.claims[].claim_no 对应 |
| `claim_text` | string | 完整原文（与 task_package 一致）|
| `comparisons` | FeatureComparison[] | 该 claim 全部 feature 的判定 |
| `claim_score` | number 0-100 | `mean(该 claim 各 feature.score) × 100`；任一"明确不满足"该 claim 直接 0 |

## FeatureComparison（含 evidence_gap_brief）

```json
{
  "feature_id": "C1-F3",
  "patent_feature": "...",
  "competitor_feature": "...",
  "status": "可能满足",
  "score": 0.8,
  "evidence": [...],
  "reasoning": "...",
  "suggested_followup_queries": [],
  "evidence_gap_brief": "还缺：...\n下一步建议：..."
}
```

字段同模块二，新增/强化：

| 字段 | 模块三阶段要求 |
|---|---|
| `suggested_followup_queries` | 终判后必须为空数组（已搜完，不再有 followup）|
| `evidence_gap_brief` | **权 1 中 status ∈ {可能满足, 证据不足} 的 feature 必填**（两行结构：还缺 / 下一步建议）；其他情况一律 `""` |

## evidence_gap_brief 格式（仅权 1 缺口 feature 必填）

两行文字：

```
还缺：<具体技术维度，写清"已有公开证据为何不足以证明本特征，还缺 XXX 才能证明该特征">
下一步建议：<明确建议去哪里（具体网站名如畅易汽车网、汽车之家、汽修巴巴等真实网站）找什么>
```

**写作要求**：
- "还缺"具体到技术维度，不能笼统写"证据不足"；同时说清"为何不足"和"还缺什么才能证明"
- "下一步建议"必须明确可执行——指定真实网站名 + 在该网站做什么动作（"定位 XX 维修手册""下载 XX 规格书""查看 XX 章节"）
- **不要写"搜 XXX"这种 query 字串**——只给方向
- 带 URL 必须是真实网站根域名，不能瞎编具体文章路径
- 不超过 2 行；每行不超过 120 字

## 关键约束

- `claim_charts` 必须按 `claim_no` 1, 2, 3, ... 顺序排列
- `claim_charts` 覆盖 task_package 中**全部权利要求**（独立 + 从属）
- 模块二已判 1.0 的权 1 feature **沿用判定** + 同 URL evidence（除非有新证据冲突）
- 模块三**不重复**模块二跑过的 query（应换思路）
- **失格只看权 1**：从属权利要求"明确不满足" → 对应 `claim_score = 0`，但**不**触发候选整体 `disqualified=true`
- `total_score = claim_1_score`（非权 1 不进 ranking 总分）
