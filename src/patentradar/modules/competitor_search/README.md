# 模块二 competitor_search

输入：模块一产出的 `task_package.json`。

输出：`step5_top5_claim1_candidates.json`，包含按权利要求1逐特征对比后的 TOP 竞品；如果有效竞品不足 5 个，不硬凑。

## 五步产物

1. `step1_query_plan.json`
   - GPT-5.5 生成 30-50 个检索 query。
   - query 覆盖权1技术特征、市场名称、规格书、行业公司、中英文表达。

2. `step2_search_results.json`
   - 调 Tavily、Bocha、Exa、Brave。
   - 每个 query 默认取前 5 条，按 URL 去重。

3. `step3_candidate_shortlist.json`
   - GPT-5.5 读取搜索摘要，合并、过滤、排除申请人产品。
   - 输出 15-30 个具体产品或具体版本。

4. `step4_candidate_evidence.json`
   - 每 5 个竞品一个批次并行处理。
   - 每个竞品先搜高复用证据，再对缺口技术特征补搜。
   - 对权1每个技术特征输出证据 URL、竞品特征、判断和分数。

5. `step5_top5_claim1_candidates.json`
   - 主流程按总分排序。
   - 第 5 名如有同分竞品，一并输出。

## 运行方式

单步跑，便于人工复核：

```bash
uv run python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --step 1
```

后续步骤会读取前一步输出：

```bash
uv run python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --step 2
```

完整跑：

```bash
uv run python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --step all
```

CLI：

```bash
uv run patentradar competitor-search \
  tests/decompose/outputs/CN114512759B/task_package.json \
  --output-dir tests/competitor_search/outputs/CN114512759B
```

## 环境变量

沿用 `.env.example`：

- `PATENTRADAR_MODEL=gpt-5.5`
- `PATENTRADAR_CONTEXT_LENGTH=258000`
- `PATENTRADAR_REASONING_EFFORT=high`
- `TAVILY_API_KEY`
- `BOCHA_API_KEY`
- `EXA_API_KEY`
- `BRAVE_API_KEY`

## 评分

每个候选总分**百分制**，最高 100 分。每条权 1 特征**平权**，权重 = `100 / 特征数`。
特征 `score` 字段是满足**比例**（非绝对分数）：

- **明确满足 1.0**：有公开 URL 直接证据，且 ≥ 2 个独立 host
- **可能满足 0.8**：由公开证据合理推理得出
- **证据不足 0.3**：证据池里没有相关线索
- **明确不满足 0.0**：有公开证据直接矛盾，整个候选 `disqualified=true`，`total_score = 0`

`total_score = mean(每条 ratio) × 100`，所以 6 条全「明确满足」= 100 分；
5 条「明确满足」+ 1 条「可能满足」≈ 96.67 分。
