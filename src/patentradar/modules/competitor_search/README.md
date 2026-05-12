# 模块二：competitor_search

> 用模块一输出的 `task_package.json` 找权利要求 1 的 TOP5 竞品，输出每个竞品对权 1 全部技术特征的逐条对比表。

输入：[`task_package.json`](../../../../tests/decompose/outputs/CN114512759B/task_package.json)（模块一产物）

输出：`step5_top5_claim1_candidates.json`，TOP5 候选 + 权 1 对比表 + 失格候选清单。**如果有效候选不足 5 个不硬凑**，TOP 数量可少于 5。

---

> **LLM backend 全局可切换**：所有 LLM 调用走 `get_llm_provider()`。默认 ChatGPT OAuth (Codex)，设置 `PATENTRADAR_LLM_BACKEND=openai` + `PATENTRADAR_OPENAI_BASE_URL` + `PATENTRADAR_OPENAI_API_KEY` 即可切到任意 OpenAI 兼容服务。模块二证据 round 1 的图片输入会在 provider 不支持 vision 时自动丢弃并打 warning。

## 五步流水线产物

### Step 1 — `step1_query_plan.json`
GPT-5.5 围绕权 1 生成 **30-50 个检索 query**，附带：
- `claim_1_summary`：一句话概括权 1 保护范围
- `applicant_self_signals`：申请人自家域名 / 中英 alias，**用于后过滤层动态黑名单**
- `queries[]`：含 `query_id` / `query` / `intent` / `language` / `target_feature_ids` / `preferred_providers`

覆盖维度：权 1 关键参数、市场俗称、产品规格书、行业头部公司、评测拆解、中英双语。

### Step 2 — `step2_search_results.json`
[`SearchRouter`](../../search/router.py) 跑每条 query，最多打 3 个 provider（按 `preferred_providers` 顺序），全局 cap 400 条结果。

**搜索结果走两层后过滤**：
- **静态层** [`configs/search_filters.toml`](../../../../configs/search_filters.toml)：专利文献站（patents.google.com / patsnap / espacenet 等）+ 文档分享站 + 寄生 URL 正则
- **动态层** [`ApplicantSelfSignals`](../../schemas/query_plan.py)：申请人自家域名 + 中英 alias 命中标题即丢

Tavily 配 10 个 key 池，429/401/403 自动轮换。Exa 用原生 `excludeDomains` 而非负向操作符（neural embedding 不支持 `-keyword`）。

### Step 3 — `step3_candidate_shortlist.json`
GPT-5.5 读 step2 搜索摘要（已过滤），输出 **15-30 个具体产品/版本**：
- `company` + `company_en` + `product_name` + `product_name_en` + `product_version`
- `source_result_ids` / `source_urls` / `initial_evidence_summary`
- 候选 ID 程序化强制为 `P01..PNN` 连续序列
- 去重 key 用 `(company, product_name, product_version)` 三元组，允许同公司不同型号

### Step 4 — `step4_candidate_evidence.json`（+ `step4_evidence_batches/batch_NN.json`）

每 5 个候选 1 batch，ThreadPoolExecutor 默认 3 并行。**单 batch 内部走两轮 LLM**：

1. **Round 1（initial）**：
   - 先 fetch step3 给的 `source_urls`（高价值 seed），再用 query 模板（中英双语）跑搜索补抓证据
   - LLM 评估权 1 7 条特征，**对每条 status ∈ {证据不足, 可能满足} 的特征输出 `suggested_followup_queries`**（每个 feature 1-3 条，单候选总上限 5 条）
2. **Gap 搜索（代码端执行 LLM 建议）**：
   - 收集 LLM 的 `suggested_followup_queries`，去重后调 `SearchRouter` 跑
   - 用 `fetch_evidence` 抓 HTML/PDF 新 URL（已有的不重抓）
   - **机械模板降级 fallback**：仅当 LLM round 1 没给任何 query 时才用 `build_gap_evidence_queries` 兜底
3. **Round 2（finalization）**：把新旧证据一起喂给 LLM，给出最终评估，`suggested_followup_queries` 必须空

**LLM 输入收紧（防 context 爆）**：
- 每候选 `search_results[:30]`（按相关性排序后取 top 30）
- 每候选 `fetched_pages[:10]` × `text[:4000]`
- 多模态图片每候选 ≤ 6 张 PNG（PDF 关键页渲染）

**证据 fetch 支持多模态**：[`fetch_evidence`](../../fetcher/web_fetcher.py) 检测 content-type，HTML 走 BS4 + 关键词窗口截取；PDF 走 [`extract_pdf_evidence`](../../fetcher/pdf.py)：按权 1 + 候选关键词定位**关键页**（≤ 5 页），每页 text 抽取量 ≥ 200 字走 text，< 200 字走 PNG 渲染（dpi=120），text + image 一起喂 LLM。

### Step 5 — `step5_top5_claim1_candidates.json`
主流程按 `total_score` 降序排：
- 第 5 名如有同分候选并列输出
- 失格（`disqualified=true`）单独放 `excluded_candidates`

---

## 评分（百分制）

每个候选 `total_score` 上限 100 分。每条权 1 特征**平权**，权重 = `100 / 特征数`。

`FeatureComparison.score` 字段是该特征的**满足比例**：

| status | ratio | 触发条件 |
|---|---|---|
| **明确满足** | **1.0** | 公开 URL 直接证据，≥ 1 独立 host（同 host 多 URL 允许，每条都得独立有价值）|
| **可能满足** | **0.8** | 由公开证据合理推理（reasoning 必须给推理链）|
| **证据不足** | **0.3** | 证据池里没有相关线索 |
| **明确不满足** | **0.0** | 公开证据直接矛盾。整个候选 `disqualified=true`，`total_score=0` |

`total_score = mean(每条 ratio) × 100`：6 特征全「明确满足」= 100；5 明确 + 1 可能 ≈ 96.67；6 特征全「证据不足」= 30。

数学约束类特征（D/V、S/E、L/S 等）必须**现场计算**写到 `competitor_feature` 字段，禁止只写"满足公式约束"这种空话。

---

## 配置入口

### `configs/`（与模块一共享）
- [`technology_tags.toml`](../../../../configs/technology_tags.toml)：9 个技术领域标签（模块一用，模块二的 step1 prompt 通过 `claim_1_summary` 间接体现）
- [`search_filters.toml`](../../../../configs/search_filters.toml)：搜索结果**静态黑名单**（专利站 / 文档站 / 寄生 URL 正则）

### `.env`
```env
PATENTRADAR_MODEL=gpt-5.5
PATENTRADAR_CONTEXT_LENGTH=258000
PATENTRADAR_REASONING_EFFORT=high
CODEX_STREAM_TIMEOUT=900

TAVILY_API_KEY=tvly-dev-key1
tvly-dev-key2,        # 可堆叠多 key（裸行），自动轮换
tvly-dev-key3,
BOCHA_API_KEY=sk-xxx
EXA_API_KEY=xxx
BRAVE_API_KEY=xxx
```

---

## 运行方式

### 单步跑（便于人工复核）

```bash
python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --output-dir tests/competitor_search/outputs/CN114512759B \
  --step 1   # 改 --step 2/3/4/5 跑后续
```

后续步骤会自动读取前一步输出。

### 完整流水线

```bash
python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --output-dir tests/competitor_search/outputs/CN114512759B \
  --step all
```

### 单候选 step4（调试 / 快速验证）

```bash
python tests/competitor_search/run_step4_single_candidate.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --shortlist tests/competitor_search/outputs/CN114512759B/step3_candidate_shortlist.json \
  --candidate-id P02 \
  --output-dir tests/competitor_search/outputs/CN114512759B/step4_single
```

### CLI（端到端）

```bash
patentradar competitor-search \
  tests/decompose/outputs/CN114512759B/task_package.json \
  --output-dir tests/competitor_search/outputs/CN114512759B \
  --max-workers 3
```

---

## 跨领域验证结果

### CN114512759B（动力电池 / 比亚迪刀片电池专利）
- step1: 50 query，applicant_self_signals 输出 BYD 17 个子品牌域名（含腾势/仰望/方程豹）
- step2: 369 结果（4 provider 均衡），BYD 0 漏过 / 专利文献 0 漏过
- step3: 18 候选（蜂巢 9 / CATL 3 / REPT 3 / 国轩 1 / 吉利 1 / 昆宇 1），EN alias 100%
- step4 P01（蜂巢 L600 196Ah）：**88.33 / 100**
  - 5 条「明确满足」+ 1 条「证据不足」（硬壳字面证据缺失）
  - D/V、S/E、L/S 数学约束全部现场计算（574×118×21.5mm + 627.2Wh）

### CN110395195B（智能座舱 / 比亚迪显示终端调节执行机构）
- step1: 50 query，机械结构维度（旋转机构/滑动/连杆/减速器）完全替换电池维度
- step2: 348 结果，整车 + 上游供应链兼有
- step3: 17 候选 / **14 不同公司**（极氪 ×2 / 高合 / 深蓝 / 上汽 / 特斯拉 / 奇点 / 兆威 ×3 / 延锋 / 三星显示 / Iskra / Harmonic Drive / Bosch），EN alias 100%
- step4 P04（高合 HiPhi Bot）：**78.0 / 100**
  - 「动力源」「触摸屏」明确满足；「偏心转动」「滑动+旋转联动」可能满足（公开资料够运动效果不够内部拓扑）；「第一/第二滑动部」证据不足（拆解图公开渠道找不到）

跨领域验证证明 prompt 完全泛化，**不依赖任何专利领域专属词汇**。

---

## 当前已知技术债

| 项 | 严重度 | 说明 |
|---|---|---|
| ~~Gap 搜索用机械模板~~ | ✅ 已修 | round 1 LLM 输出 `suggested_followup_queries`，代码端按 LLM 建议跑 gap；机械模板降级为 fallback。模块二聚焦权 1，模块三在更全视角下再补一次（递进式）。模块二 round 2 的 `CandidateEvidence.searched_queries` 字段会记录实际跑过的 query 历史，**模块三 round 1 会读到这份历史并主动避免字面重复**（防止两个模块对同一缺口跑相同 query 浪费 API 配额）。 |
| 无搜索/fetch 缓存 | 🟡 中 | 同一专利反复跑 step4 会重复 API 调用 |
| Tavily key 池静态读 `.env` | 🟢 低 | 想加更多 key 需重启进程 |
| 单候选 step4 ~8 分钟 | 🟢 低 | ChatGPT 配额是主要瓶颈，已通过 truncate + key 池缓解 |

---

## 文件清单

```
src/patentradar/
├── cli.py                                # `patentradar competitor-search` 入口
├── modules/competitor_search/
│   ├── pipeline.py                       # 五步编排
│   ├── query_generator.py                # step1 包装
│   ├── candidate_discovery.py            # step2 包装
│   ├── candidate_filter.py               # step3 包装
│   ├── evidence_mapper.py                # step4 双轮证据 + LLM 调用
│   ├── evidence_search.py                # step4 query 模板 + fetch
│   ├── scorer.py                         # step5 排序 + 同分并列
│   ├── stop_rules.py                     # 证据充分 / 重复来源等停止条件
│   └── README.md                         # 本文件
├── llm/
│   ├── prompts/
│   │   ├── query_generation.md           # step1 prompt
│   │   ├── candidate_extract.md          # step3 prompt
│   │   └── evidence_extract.md           # step4 prompt
│   └── workers/
│       ├── query_worker.py               # step1 LLM 包装
│       ├── candidate_worker.py           # step3 LLM 包装 + candidate_id 兜底
│       └── evidence_worker.py            # step4 LLM 包装 + 相关性排序 + multimodal
├── search/
│   ├── router.py                         # 多 provider 路由 + 全局过滤
│   ├── filters.py                        # 静态 + 动态后过滤层
│   ├── relevance.py                      # 关键词命中度排序
│   ├── tavily.py / bocha.py / exa.py / brave.py
│   └── result_normalizer.py
├── schemas/
│   ├── query_plan.py                     # QueryPlan + ApplicantSelfSignals
│   ├── search_result.py                  # SearchResult
│   ├── candidate.py                      # Candidate + 中英 alias
│   └── evidence.py                       # FeatureComparison + CandidateEvidence + TopCompetitorReport
└── fetcher/
    ├── web_fetcher.py                    # HTML / PDF 统一 fetch（多模态）
    └── pdf.py                            # PDF 关键页定位 + text/image 分流

configs/
├── search_filters.toml                   # 静态黑名单
└── technology_tags.toml                  # 9 个技术领域标签（共享）

tests/competitor_search/
├── run_competitor_search_steps.py        # step1-5 单步/全跑入口
├── run_step4_single_candidate.py         # 单候选 step4 调试入口
└── outputs/
    └── <publication_no>/
        ├── step1_query_plan.json
        ├── step2_search_results.json
        ├── step3_candidate_shortlist.json
        ├── step4_evidence_batches/batch_NN.json
        ├── step4_candidate_evidence.json
        └── step5_top5_claim1_candidates.json
```
