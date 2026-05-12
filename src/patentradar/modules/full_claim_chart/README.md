# 模块三：full_claim_chart

> 模块二用权 1 找到 TOP5 候选，**模块三把这 TOP5 的对比扩展到全部权利要求**，输出完整的 claim chart。
>
> 评分仍只看权 1（同模块二）；非权 1 的对比是为了报告**完整性**，不进入 ranking。

输入：
- 模块一 [`task_package.json`](../../../../tests/decompose/outputs/CN114512759B/task_package.json)（全部权利要求 + 全部特征）
- 模块二 `step5_top5_claim1_candidates.json`（TOP5 候选 + 权 1 对比表 + 已收集证据）

输出：[`top5_full_claim_chart.json`](../../../../tests/full_claim_chart/outputs/) —— TOP5 候选 + 全部权利要求逐特征对比。

---

## 与模块二的递进式 gap 搜索

模块二和模块三都用 `suggested_followup_queries` 字段让 LLM 主动指挥代码端做 gap 搜索：

| 阶段 | 焦点 | LLM 主动 gap 搜索 |
|---|---|---|
| 模块二 round 1 | 权 1 initial 证据 | 输出 `suggested_followup_queries`（仅权 1 缺口）|
| 模块二 round 2 | 权 1 + LLM 建议补搜的新证据 | 不再提议 |
| 模块三 round 1 | 拿模块二证据池 + 权 1 判断 → 评估**全部 claims** | 输出 `suggested_followup_queries`（权 1 缺口 3-5 / 非权 1 缺口 1-2）|
| 模块三 round 2 | 全证据池 finalize | 不再提议 |

**递进式效果**：
- 权 1 在模块二、模块三各被主动搜索一次 = 2 次主动 gap
- 非权 1 仅在模块三被主动搜索一次 = 1 次主动 gap

这符合"重点在权 1，非权 1 仅作完整性补充"的核心原则。

### 跨模块 query 去重（防重复）

两个模块用同一套 `suggested_followup_queries` 机制，可能对同一缺口提出字面相同的 query 浪费 API 调用。**双层去重**：

1. **Prompt 层（LLM 主动避免）**：模块三 round 1 user_text 里包含 `module_two_evidence.queries_already_tried_in_module_two`（来自模块二的 `CandidateEvidence.searched_queries`）。Prompt 明确告诉 LLM：「模块二已经跑过这些 query 但没拿到新证据，**不要重复**，换思路（换语言 / 换关键词组合 / 换具体型号 / 换证据形式如规格书 vs 评测 vs 拆解视频）。」
2. **代码层兜底**：[`_collect_suggested_queries`](pipeline.py) 收集 LLM round 1 输出后，与 `module_two_evidence.searched_queries` 做 case-insensitive + trim 后字符串对比，命中即跳过，并打 INFO 日志记录跳过数。

**额外**：URL 级别已经有去重（`pool_url_set`），所以即便上面两层都失效，模块三也不会重复 fetch 同一 URL。

> **LLM backend 全局可切换**：所有 LLM 调用走 `get_llm_provider()`。默认 ChatGPT OAuth (Codex)，设置 `PATENTRADAR_LLM_BACKEND=openai` + `PATENTRADAR_OPENAI_BASE_URL` + `PATENTRADAR_OPENAI_API_KEY` 即可切到 OpenAI 兼容服务；evidence_pool 图片在 provider 不支持 vision 时自动丢弃并打 warning。

## 工作流（每候选 2 轮 LLM 调用，TOP5 并行）

```
候选 P01:
  Round 1 (复用 + 提议):
    LLM 看：模块一全部 claims + 候选信息 + 模块二的权 1 证据池
    LLM 输出：
      - 对**全部 claim 全部 feature** 给 FeatureComparison（先复用现有证据）
      - 对每条 status ∈ {证据不足, 可能满足} 的 feature 输出 `suggested_followup_queries`
        （权 1 缺口每条 3-5 query，非权 1 缺口每条 1-2 query，单候选总上限 30）
    ↓
  Gap search (代码端执行 LLM 的 query):
    用 SearchRouter 跑 LLM 建议的 query，按 ApplicantSelfSignals 过滤
    fetch_evidence 抓 HTML/PDF，新 URL 加进证据池（已有 URL 不重抓）
    ↓
  Round 2 (定稿):
    is_finalization_round=True，把新旧证据一起喂给 LLM
    LLM 输出最终 FullClaimChartCandidate（suggested_followup_queries=[]）

5 个候选 ThreadPoolExecutor 默认 2 并行 → 共 ~10 次 LLM 调用 / 专利
```

## Schema 设计

- 复用模块二的 `FeatureComparison`（pattern 放宽到 `^C\d+-F\d+$`，加了 `suggested_followup_queries` 字段，模块二/三共用）
- 新增 [`ClaimChartEntry`](../../schemas/claim_chart.py)：一条权利要求 + 其全部 feature 的 FeatureComparison + `claim_score`
- 新增 [`FullClaimChartCandidate`](../../schemas/claim_chart.py)：候选 + 全部 ClaimChartEntry + 两个分数：
  - `claim_1_score`：权 1 的 `claim_score`
  - `total_score`：**= claim_1_score**（**只看权 1**）
- 新增 [`FullClaimChartReport`](../../schemas/claim_chart.py)：所有 TOP5 候选 + 失格列表

## 评分（核心：只看权 1）

每条 feature 仍是 `1.0 / 0.8 / 0.3 / 0.0` 比例，沿用模块二：

| status | ratio | 触发条件 |
|---|---|---|
| 明确满足 | 1.0 | 公开 URL 直接证据，≥ 1 独立 host |
| 可能满足 | 0.8 | 由公开证据严谨推理 |
| 证据不足 | 0.3 | 证据池里找不到相关线索 |
| 明确不满足 | 0.0 | 公开证据直接矛盾 → 整个候选 disqualified |

每条 claim 的分：
```
claim_score = mean(该 claim 各 feature.score) × 100
任一 feature 「明确不满足」→ claim_score = 0
```

候选总分：
```
total_score = claim_1_score（只看权 1）
```

**为什么只看权 1**：
- 权 1 是最广的保护范围；从属权利要求是下位限定，不影响"是否侵权"的核心判断
- 保持和模块二评分一致，避免权 1 已经明确满足的候选因从属权利要求证据不足被压低
- 非权 1 的 `claim_score` 在每个 `ClaimChartEntry` 里**保留**，供模块四报告完整展示，但**不参与 total_score**

**失格**仍然看全部 claims：任一 claim 任一 feature 「明确不满足」→ `disqualified=true`, `total_score=0`。

## 复用模块二证据池

模块二在 step4 抓的 URL/text/image 已经在 `CandidateEvidence.comparisons[*].evidence[*]` 里。模块三 Round 1 把这些直接喂给 LLM 作为初始证据池，**不需要重新抓**。

唯一遗憾：模块二的 `TopCompetitorReport` 没保存原始抓到的网页正文（只保存了 `EvidenceSource.snippet`），所以模块三看到的复用证据其实是 snippet 级别，不是全文。如果 snippet 不够，模块三的 gap search 会主动补抓全文。

## 失格

- 模块二判定的 `disqualified=true` 会被模块三**直接复用**，不重新查 launch_date
- 但模块三 round 2 如果拿到新证据明确不满足某条 feature，会把候选 disqualified=true

## 配额预算

- 每候选 2 次 LLM call × 5 候选 = **10 次 GPT-5.5 调用 / 专利**
- gap search：每候选最多 30 query × 4 provider = 120 次 search API 调用 / 候选
- 假设 ChatGPT 3 小时窗口约 80 条 GPT-5.5 → 单专利 10 次远低于阈值

---

## 运行方式

### 全 TOP5（step5 已存在）

```bash
python tests/full_claim_chart/run_full_claim_chart.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --top-report   tests/competitor_search/outputs/CN114512759B/step5_top5_claim1_candidates.json \
  --output-dir   tests/full_claim_chart/outputs/CN114512759B
```

### 单候选（调试）

```bash
python tests/full_claim_chart/run_full_claim_chart.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --top-report   tests/competitor_search/outputs/CN114512759B/step5_top5_claim1_candidates.json \
  --candidate-id P01 \
  --output-dir   tests/full_claim_chart/outputs/CN114512759B
```

### 没跑模块二 step5 时（fallback：从 step4 bootstrap）

```bash
python tests/full_claim_chart/run_full_claim_chart.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --candidate-evidence tests/competitor_search/outputs/CN114512759B/step4_candidate_evidence.json \
  --candidate-id P01 \
  --output-dir   tests/full_claim_chart/outputs/CN114512759B
```

### CLI

```bash
patentradar full-claim-chart \
  tests/decompose/outputs/CN114512759B/task_package.json \
  tests/competitor_search/outputs/CN114512759B/step5_top5_claim1_candidates.json \
  --output-dir data/output/CN114512759B \
  --max-workers 2
```

---

## 输出文件结构

```
tests/full_claim_chart/outputs/CN114512759B/
├── top5_full_claim_chart.json          # 最终 FullClaimChartReport
└── candidates/                          # 每候选的中间产物（便于人工复核）
    ├── P01_round1.json                  # round 1: 含 suggested_followup_queries
    ├── P01_round2.json                  # round 2: 定稿
    ├── P02_round1.json
    ├── P02_round2.json
    └── ...
```

## 后续模块

模块四 `report` 将读 `top5_full_claim_chart.json` 生成可人工复核的 Markdown 报告：
- TOP5 排序（按 total_score）
- 每个候选一节：候选信息 + 全部权利要求逐条对比表 + 证据 URL
- 失格候选附录（含 disqualification_reason）
