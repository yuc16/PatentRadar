# PatentRadar v2

> 用户输入专利公开号，系统自动围绕权利要求 1 挖掘可能落入其技术特征保护范围的竞品，并输出 TOP5 候选竞品的详细对比报告。

当前仓库已交付 **模块一：decompose（专利拆解）**。模块二/三/四正在规划中。本 README 详细说明模块一实现了什么、怎么实现、Codex 在我的代码审查后做了哪些优化、以及还有哪些点没有覆盖。

---

## 1. 模块一做了什么

**输入**：一个中国专利公开号（含 Google Patents 链接、`CN-105335144-B`、`CN 114512759 B` 等常见变体）。

**输出**：一个结构化的 `task_package.json`，包含：

| 字段 | 含义 |
|---|---|
| `patent` | 专利基础信息：公开号、标题、申请人（中文）、发明人、申请日、Google Patents 链接、官方 PDF 链接、抓取时间 |
| `technology_tag` | 9 类技术领域标签之一：动力电池 / 电驱系统 / 充配电系统 / 整车与车身底盘 / 智能驾驶 / 智能座舱与车联网 / 制造工艺与装备 / 材料与化学 / 其他 |
| `claims` | 全部权利要求，每条含完整原文 `claim_text` 和拆解后的原子特征列表 `features` |
| `claim_1_text` / `claim_1_features` | 权利要求 1 的冗余字段（下游高频访问） |
| `claims_source` | `html` 或 `pdf_vision`，指示来源 |
| `model` / `reasoning_effort` | 实际使用的 LLM 配置 |

每个 `feature` 形如：

```json
{
  "feature_id": "C1-F3",
  "feature_text": "所述电池本体的厚度D与所述电池本体的体积V满足：D/V= 0.0000065 mm⁻² ~ 0.00002 mm⁻²"
}
```

`feature_id` 强约束为 `C{claim_no}-F{idx}` 格式，方便模块二/三/四引用。

---

## 2. 怎么实现的

### 2.1 流程

```
公开号
  ↓ 公开号规范化（支持 URL/带空格/带横线）
  ↓
fetcher.google_patents.fetch_patent
  ├─ HTTP GET https://patents.google.com/patent/<pub>/zh
  ├─ 抽取 <section itemprop="claims"> 里 <div class="claims" lang="ZH">
  ├─ 抓申请人（assigneeOriginal 优先取中文，fallback 英文别名映射）
  └─ 检测 patent-image-not-available 占位符
        │
        ├─ 无占位 → HTML 路径
        │     ↓
        └─ 有占位 → fetcher.pdf 下载官方 PDF + 渲染权利要求页 PNG → PDF Vision 路径
                 ↓
llm.workers.decompose_worker.decompose_claims
  ├─ system prompt：13 条规则 + 7 个示例
  ├─ ChatGPT Codex Responses SSE 调用（OAuth via ~/.codex/auth.json）
  ├─ JSON Schema strict 模式约束输出（含 feature_id pattern）
  ├─ 自动重试可恢复错误（429/timeout/transport，最多 3 次，退避 20/40s）
  └─ 输出后做 _normalize_feature_ids 兜底，强制改写 ID 格式
        ↓
schemas.TaskPackage (Pydantic v2 校验)
        ↓
落盘 task_package.json + 写入 INFO 日志（含 elapsed_ms / tag / source）
```

### 2.2 代码结构

```
src/patentradar/
├── cli.py                                # `patentradar decompose <pub>` 入口
├── core/
│   ├── constants.py                      # 模型名、9 个技术标签
│   └── exceptions.py                     # PatentFetchError / LLMOutputError
├── schemas/
│   ├── patent.py                         # PatentInfo
│   ├── claims.py                         # Claim, ClaimFeature（pattern=^C\d+-F\d+$）
│   └── task_package.py                   # TaskPackage（含字段校验）
├── fetcher/
│   ├── google_patents.py                 # HTML 抓取 + claim 提取 + 申请人 alias
│   └── pdf.py                            # PDF 下载 + 权利要求页渲染 (PyMuPDF)
├── llm/
│   ├── codex.py                          # ChatGPT Codex SSE 客户端 + 公式/图片支持
│   ├── prompts/decompose.md              # 13 规则 + 7 示例的 system prompt
│   └── workers/decompose_worker.py       # Schema + 强校验 + ID 兜底
└── modules/decompose/
    └── pipeline.py                       # 编排 fetch → vision? → LLM → 落盘
```

### 2.3 拆解规则（prompt 节选）

13 条规则覆盖：

1. **忠于原文 + 错别字保守修正豁免**：明显的多字/漏字/字符顺序颠倒/形近字误植允许在 `claim_text` 与 `feature_text` 中一致地修正；模糊判断保留原文，禁止泛化/补写/近义替换。
2. 完整 `claim_text` 保留；公式按 LaTeX `$...$` / `$$...$$` 还原。
3. `feature_text` 必须是 `claim_text` 中的连续片段。
4. **前序处理**：仅在含「其特征在于」的权利要求里识别前序并删除；没有「其特征在于」的简短产品权利要求（如 "一种终端设备，包括：…"）保留主题。
5. **引用条款剥离**："如权利要求 X-Y 任一项所述的"等依赖关系声明不作为 feature。
6. **if-else 整体保留**：触发条件 + then 分支 + else 分支必须合并为一条。
7. **同一步骤内连续动作合并**：投射→检测→反馈这种因果链作为一条；只有可独立验证的算法/基准值定义另起一条。
8. 并列部件按可独立判断的原子特征拆分，同一部件的位置/连接/内部组成/功能合并为一条。
9. "用于…" 功能描述附在所属部件上，不单独成条。
10. **公式 + 变量定义合并**：禁止把变量定义拆出去。
11. 独立权利要求 4–10 条特征，从属权利要求 1–3 条。
12. 不机械按逗号分号过度切分。
13. `feature_id` 必须是 `C{claim_no}-F{idx}` 格式。

7 个示例分别对照「前序」「前序例外」「引用条款」「if-else」「连续动作」「公式合并」「数值参数粒度」六个最易漂移的规则。

---

## 3. Codex 在审查后做了哪些优化

我做完代码审查后提了一份清单，由 Codex 在 commit `702e910` 中实现。共 7 项落地：

### ✅ 3.1 公开号规范化更宽松
[`google_patents.py:normalize_publication_no`](src/patentradar/fetcher/google_patents.py)

支持以下输入：
- `CN105335144B`
- `CN-105335144-B`
- `CN 105335144 B`
- `https://patents.google.com/patent/CN105335144B/zh`

并新增 unit test 覆盖。

### ✅ 3.2 申请人/发明人改用中文
[`google_patents.py:_main_dd_texts`](src/patentradar/fetcher/google_patents.py) + `_prefer_cn_aliases`

抓取顺序：
1. 优先从 `<dd itemprop="assigneeOriginal">` 取中文原始名（绝大多数中国专利覆盖）；
2. fallback 到 `<meta DC.contributor scheme="assignee">`，再用 `_CN_ASSIGNEE_ALIASES`（目前覆盖 3 个 BYD 实体）映射。

效果：`CN107423660B` → `比亚迪半导体股份有限公司`（之前是 `BYD Semiconductor Co Ltd`），下游中文搜索召回率显著提升。

### ✅ 3.3 HTML claim 提取更鲁棒
[`google_patents.py:_extract_claims`](src/patentradar/fetcher/google_patents.py)

- 优先选择 `<div class="claims" lang="ZH">`，避免中英对照页面里抽到英文；
- 用 `(claim_no, claim_text[:30])` 去重，避免 `cl0XX` / `zh-cl0XX` 重复匹配。

### ✅ 3.4 PDF Vision 校验放宽
[`decompose_worker.py:_validate_against_html`](src/patentradar/llm/workers/decompose_worker.py)

- HTML 路径：LLM 输出条数与编号必须严格等于 HTML 提取结果；
- PDF Vision 路径：只要 LLM 条数 `>= HTML 条数`、且前缀编号一致即可。

修复了"HTML 因占位缺失某条 → PDF 修复反而被拒绝"的潜在问题。

### ✅ 3.5 `feature_id` 三层防御
[`decompose_worker.py`](src/patentradar/llm/workers/decompose_worker.py) + [`schemas/claims.py`](src/patentradar/schemas/claims.py)

1. **OpenAI JSON Schema strict 层**：`"pattern": "^C\\d+-F\\d+$"` 让模型生成时就受约束；
2. **Pydantic 字段层**：`Field(pattern=r"^C\d+-F\d+$")` 防御反序列化；
3. **`_normalize_feature_ids` 兜底层**：在 schema 校验前根据 `claim_no` 与 index 强制重写。

即便模型漂移，最终输出 100% 是 `C{n}-F{m}` 格式。

### ✅ 3.6 PDF Vision 路径 + 完成日志
[`pipeline.py`](src/patentradar/modules/decompose/pipeline.py)

- PDF Vision 触发时打 `INFO` 日志（含 publication_no / claim_count / pdf_url 是否非空）；
- 整体完成打 `INFO` 日志（含 elapsed_ms / source / claim_count / technology_tag）。

### ✅ 3.7 入口收敛
- 删除冗余的 `scripts/run_decompose.py`；
- 统一为 `patentradar decompose <pub>` CLI；
- CLI 在写出目录时也调用 `normalize_publication_no` 保证一致。

---

## 4. 全量验证结果

[`tests/decompose/run_full_pool_decompose.py`](tests/decompose/run_full_pool_decompose.py) 跑完了候选池 **238 篇专利**的全量端到端，输出在 [`tests/decompose/outputs/`](tests/decompose/outputs/)，汇总在 [`tests/decompose/results/`](tests/decompose/results/)。

### 4.1 结果总览

| 指标 | 数值 |
|---|---|
| 总专利数 | **238** |
| 成功 | **238** |
| 失败 | **0** |
| HTML 路径 | 234 篇（98.3%）|
| PDF Vision 路径 | 4 篇（1.7%）|
| 总耗时 | 4 小时 22 分（含每篇 2s 节流）|
| 单篇耗时 | 中位 60.3s / 平均 64.3s / 最长 137.5s |
| 累计权利要求 | ~3500 条（中位 14 / 平均 14.6 / 最长 30）|
| 累计原子特征 | **7251** 个（中位 28 / 平均 30.5）|

### 4.2 9 类技术标签分布（238 篇）

| 标签 | 数量 |
|---|---|
| 其他 | 100 |
| 智能座舱与车联网 | 50 |
| 整车与车身底盘 | 44 |
| 充配电系统 | 23 |
| 智能驾驶 | 13 |
| 电驱系统 | 5 |
| 动力电池 | 2 |
| 制造工艺与装备 | 1 |
| 材料与化学 | 0 |

候选池由比亚迪相关专利构成，分布合理。

### 4.3 关键拆解效果验收

以 `CN107423660B`（含公式 + HTML 图片占位 + PDF Vision 路径）为例：

| 项 | 结果 |
|---|---|
| 申请人 | `比亚迪半导体股份有限公司` ✅（已中文化）|
| 来源 | `pdf_vision` ✅（多模态生效）|
| `feature_id` 格式 | `C1-F1` … `C1-F8` ✅（统一格式）|
| 权 7 拆解 | `一种终端设备，包括：指纹识别装置` ✅（前序例外正确生效，主题保留，"如权利要求1-5中任一项"剥离）|
| 公式 | `$$X'=X-a*X_j$$` + `$$a=\frac{X_z}{b}$$` ✅（公式与变量定义合并为单一 feature）|

---

## 5. 还有哪些细节没优化（已知技术债）

按优先级从高到低：

### 🟡 5.1 没有 LLM 输出缓存
- **现状**：每次调用都重新请求 ChatGPT Codex；本次 238 篇全量跑触顶过 2 次 ChatGPT 配额（一共纯等待约 5 小时）。
- **影响**：开发期反复跑 E2E 成本高；模块二开发时如需重新抓取 task_package 会再触发。
- **建议**：以 `(publication_no, prompt_hash, model)` 为 key 加缓存层，命中直接返回，提供 `--no-cache` 强制刷新。

### 🟡 5.2 LLM schema 校验失败不会自修复
- **现状**：`chat_json` 只对网络/限流类错误重试，碰到 schema 校验失败直接抛 `LLMOutputError`。
- **影响**：238 篇里没遇到，但属于潜在脆弱点。
- **建议**：把 `LLMOutputError` 也纳入 1 次重试，重提时附上"上一轮的错误信息 + 字段位置"作为 self-repair 提示。

### 🟡 5.3 PDF 选页规则用 marker 扫描，不够鲁棒
- **现状**：[`pdf.py:render_claim_pages`](src/patentradar/fetcher/pdf.py) 用「`权利要求书`」+「`说明书`」关键词找页边界。
- **风险**：极少数 PDF 把「权利要求书」印在页眉每页都命中；或单页同时含权利要求结尾 + 说明书开头会被截断。本次 4 篇 PDF Vision 都没踩到。
- **建议**：改为定位「权利要求书」首次出现页 → 「说明书」/「附图说明」首次出现页 之间的 range 切片。

### 🟡 5.4 `pdf_url` 为空且有图片占位时直接报错
- **现状**：[`pipeline.py`](src/patentradar/modules/decompose/pipeline.py) 在 `has_claim_image_placeholders=True` 但 Google 没收录 PDF 时抛 `PatentFetchError`。
- **影响**：少数边角专利无法处理。
- **建议**：增加一个 fallback —— 在 prompt 里告知 LLM "HTML 含占位但 PDF 不可得，按 HTML 原样拆解并标注异常条目"，而非整体失败。

### 🟡 5.5 申请人 alias 字典只有 3 个 BYD 实体
- **现状**：[`google_patents.py:_CN_ASSIGNEE_ALIASES`](src/patentradar/fetcher/google_patents.py) 硬编码。
- **缓解**：因为 `assigneeOriginal` 直接取中文已经覆盖绝大多数情况，alias 表实际很少触发。
- **建议**：等模块二在非 BYD 专利上遇到中文化失败时再补；不阻塞当前任务。

### 🟡 5.6 测试覆盖收敛
- **现状**：删除了 `test_decompose.py` / `test_claims_fetch_pool.py`，只保留 [`run_full_pool_decompose.py`](tests/decompose/run_full_pool_decompose.py) 的全量 E2E。
- **影响**：单元级回归（normalize_publication_no、HTML claim 抽取、申请人映射）不再有快速测试，全量 E2E 耗时长且烧 LLM 配额。
- **建议**：之后在 [`tests/decompose/`](tests/decompose/) 加一个 `test_unit.py`，把不依赖 LLM 的 fetcher / schema / normalize 单测补回来，给 CI 用。

### 🟡 5.7 错别字修正规则尚未在大样本上深度抽查
- **现状**：本次 238 篇全量跑前已加入「错别字保守修正」豁免规则（rule 1），但没有系统地比对 LLM 修正了哪些字。
- **建议**：写一个 diff 工具，把 `claim_text`（拆解后）与从 Google Patents 重新抓取的原始 HTML 文本做字符级 diff，列出所有差异，人工抽查是否都属于"明显错别字"范围。

---

## 6. 用法

### 6.1 安装

```bash
uv sync
```

### 6.2 ChatGPT Codex 认证

模块一调用的是 ChatGPT 后端 Codex Responses 端点（不是公开 OpenAI API），依赖本地 Codex CLI 登录态：

```bash
codex login
# 写入 ~/.codex/auth.json，需 ChatGPT Plus/Pro 订阅
```

### 6.3 单专利拆解

```bash
patentradar decompose CN114512759B --output-dir data/output
# 输出: data/output/CN114512759B/task_package.json
```

或用 Python API：

```python
from patentradar.modules.decompose import run_decompose
pkg = run_decompose("CN114512759B", output_dir="data/output/CN114512759B")
```

### 6.4 全量 238 篇端到端

```bash
python tests/decompose/run_full_pool_decompose.py
# 断点续跑：已存在 task_package.json 的专利自动跳过
# 配额自愈：触顶时 sleep 30 分钟后重试，最多 12 次
```

输出：
- `tests/decompose/outputs/<pub>/task_package.json` × 238
- `tests/decompose/results/full_pool_e2e_summary.json`
- `tests/decompose/results/full_pool_e2e_results.csv`
- `tests/decompose/results/full_pool_e2e.log`

### 6.5 环境变量

```env
PATENTRADAR_MODEL=gpt-5.5
PATENTRADAR_CONTEXT_LENGTH=258000
PATENTRADAR_REASONING_EFFORT=high
CODEX_STREAM_TIMEOUT=900

# 模块二预留
TAVILY_API_KEY=
BOCHA_API_KEY=
EXA_API_KEY=
BRAVE_API_KEY=
```

---

## 7. 后续模块（未实现）

- **模块二 `competitor_search`**：基于权利要求 1 多角度生成 30–50 个 query → 调用 Tavily/Bocha/Exa/Brave 搜索 → 子 agent 并行收集证据 → 输出 TOP5 竞品 + 权利要求 1 对比表。
- **模块三 `full_claim_chart`**：复用模块二证据，对 TOP5 补全所有权利要求的完整 claim chart。
- **模块四 `report`**：把模块三的结果整理为可人工复核的 Markdown 报告。
