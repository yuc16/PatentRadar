# 模块一：decompose（专利拆解）

> 用户输入专利公开号，系统自动围绕权利要求 1 挖掘可能落入其技术特征保护范围的竞品，并输出 TOP5 候选竞品的详细对比报告。本模块负责整个流水线的**第一步**：把一个专利公开号转换成结构化、可逐条比对的 `task_package.json`。

本 README 详细说明：
1. 模块一实现了什么
2. 怎么实现的
3. 经过两轮代码审查 + LLM 输出审查后做了哪些优化
4. 全量验证结果（239 篇专利）
5. 还有哪些细节没优化

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
  ├─ system prompt：13 条规则 + 8 个示例
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
│   ├── prompts/decompose.md              # 13 规则 + 8 示例的 system prompt
│   └── workers/decompose_worker.py       # Schema + 强校验 + ID 兜底
└── modules/decompose/
    ├── pipeline.py                       # 编排 fetch → vision? → LLM → 落盘
    └── README.md                         # 本文件
```

### 2.3 拆解规则（prompt 节选）

13 条规则覆盖：

1. **忠于原文 + 错别字保守修正豁免**：明显的多字/漏字/字符顺序颠倒/形近字误植允许在 `claim_text` 与 `feature_text` 中一致地修正；模糊判断保留原文，禁止泛化/补写/近义替换。
2. 完整 `claim_text` 保留；公式按 LaTeX `$...$` / `$$...$$` 还原。
3. `feature_text` 必须是 `claim_text` 中的连续片段（按规则 1 修正后以修正版为准）。
4. **前序处理 + 主题保留**：分两情况判别 ——
   - **(a) 实质型独立权利要求**（多步技术限定）：删除「一种 XX，其特征在于，」前序；
   - **(b) 简短产品/装置/介质/车辆型权利要求**（无论是否含「其特征在于」）：剩余实质内容仅是「包括 YY」时，主题（车辆/控制器/电机 等）必须保留，输出形如「一种 XX，包括：YY」。
5. **引用条款剥离**：「如权利要求 X-Y 任一项所述的」等依赖关系声明不作为 feature。
6. **if-else 整体保留**：触发条件 + then 分支 + else 分支必须合并为一条。
7. **同一步骤内连续动作合并**：投射→检测→反馈这种因果链作为一条；只有可独立验证的算法/基准值定义另起一条。
8. **同部件多侧面合并**（防 over-split）：同一部件名的列举 + 形状 + 位置 + 连接 + 内部组成 + 功能合并为一条；只有出现新部件名或新独立结构关系时才另起一条。
9. "用于…" 功能描述附在所属部件上，不单独成条。
10. **公式 + 变量定义合并**：变量定义无论在公式之前还是之后都属于该公式的不可分割部分，必须与公式同条。
11. 独立权利要求 4–10 条特征，从属权利要求 1–3 条。
12. 不机械按逗号分号过度切分。
13. `feature_id` 必须是 `C{claim_no}-F{idx}` 格式。

8 个示例覆盖最易漂移的规则：前序、前序例外（含/不含「其特征在于」两种语法）、引用条款、if-else、连续动作、公式合并（含前置/后置变量定义）、数值参数粒度、**同部件合并防 over-split**。

---

## 3. 经过的优化轮次

### 第一轮：Codex 实施代码审查清单（commit `702e910`）—— 7 项

| # | 优化点 | 文件 |
|---|---|---|
| 1 | 公开号规范化支持 `CN-105335144-B`、`CN 114512759 B`、Google Patents URL | [`google_patents.py`](../../fetcher/google_patents.py) `normalize_publication_no` |
| 2 | 申请人/发明人优先取 `<dd itemprop="assigneeOriginal">` 中文原文，fallback 英文 + 3 个 BYD 别名映射 | [`google_patents.py`](../../fetcher/google_patents.py) `_main_dd_texts` + `_prefer_cn_aliases` |
| 3 | HTML claim 提取：优先 `<div class="claims" lang="ZH">` + `(claim_no, claim_text[:30])` 去重 | [`google_patents.py`](../../fetcher/google_patents.py) `_extract_claims` |
| 4 | PDF Vision 校验放宽为 `LLM ≥ HTML`、前缀编号一致 | [`decompose_worker.py`](../../llm/workers/decompose_worker.py) `_validate_against_html` |
| 5 | `feature_id` **三层防御**：JSON Schema `pattern` + Pydantic `Field(pattern=...)` + worker 兜底 `_normalize_feature_ids` | [`decompose_worker.py`](../../llm/workers/decompose_worker.py) + [`schemas/claims.py`](../../schemas/claims.py) |
| 6 | PDF Vision 触发 / 完成日志（含 `elapsed_ms` / `tag` / `source`） | [`pipeline.py`](pipeline.py) |
| 7 | 入口收敛：删除 `scripts/run_decompose.py`，统一为 `patentradar decompose <pub>` CLI | [`cli.py`](../../cli.py) |

### 第二轮：LLM 输出抽样审查 + prompt 强化（4 项）

跑完全量 238 篇后抽 5 篇代表样本审查 LLM 拆解效果，发现 4 类系统性问题。改 [`prompts/decompose.md`](../../llm/prompts/decompose.md)：

| # | 问题 | 修复 |
|---|---|---|
| 1 | **简短产品权利要求主题被吃掉**（"一种车辆，其特征在于，包括温控系统" → 只剩 "包括温控系统"）| 重写规则 4，分 (a) 实质型 / (b) 简短产品型，主题必须保留；扩展示例 2 覆盖含/不含「其特征在于」两种语法变体 + 5 个高频踩坑案例 |
| 2 | **同部件被 over-split**（部件名 + 位置 + 内部组成被按句号拆 2-3 条）| 强化规则 8 + 新增**示例 8**：3 个同部件合并案例 + 与示例 7 的边界口诀 |
| 3 | **前置变量定义未与公式合并**（"其中 R 为...V 为..."在公式之前出现时被留在前一条 feature）| 强化规则 10：变量定义无论在公式前后都必须与公式同条；示例 6 补充前置变量定义变体（用 RV 公式示意） |
| 4 | **错别字未修正**（"包根据括"等明显排印错误被忠实保留导致下游不可读）| 改写规则 1：允许极有把握的字符级 OCR/排印错误保守修正（多字/漏字/形近字误植），明确禁止泛化/近义替换/单位规范化 |

### 第二轮验收

prompt 改完后重跑 6 篇验证（5 原审样本 + 新增 CN114512759B），所有 4 类问题全部修复：

| 专利 | 总特征数前→后 | 关键验收 |
|---|---|---|
| CN114512759B | 22 → **19** | 错别字「包根据括」→「包括」、「和和厚度」→「和厚度」；权 11「**一种电动车，包括：动力电池包**」 |
| CN116338695B | 25 → **22** | 公式 + R/V/V0/X0 全部变量定义合并到 `C1-F5` 一条 |
| CN118629013B | 57 → **53** | 权 23「一种控制器，包括存储器、处理器…」/ 权 24「一种车辆，包括：控制器」/ 权 25「一种计算机可读存储介质，…」全部带主题 |
| CN222347108U | 19 → **14** | 权 1 由 6→3 条（方向盘/转向管柱/转气回环装置），同部件合并到位；权 11「**一种车辆，包括温控系统**」 |
| CN222356050U | 37 → **29** | 权 23/24/25/26 主题四连保留（电机/压缩机/热管理系统/车辆） |
| CN223023340U | 55 → **29** | 权 1 由 6→3 条，权 15「**一种电池总成，包括：热管理系统**」 |

6 篇平均特征数下降 **~25%**，核心是消除了 over-split 与丢主题。

---

## 4. 全量验证结果

[`tests/decompose/run_full_pool_decompose.py`](../../../../tests/decompose/run_full_pool_decompose.py) 跑完了候选池 **239 篇专利**的全量端到端，输出在 [`tests/decompose/outputs/`](../../../../tests/decompose/outputs/)，汇总在 [`tests/decompose/results/`](../../../../tests/decompose/results/)。

### 4.1 结果总览

| 指标 | 数值 |
|---|---|
| 总专利数 | **239** |
| 成功 | **239** |
| 失败 | **0** |
| HTML 路径 | 235 篇（98.3%）|
| PDF Vision 路径 | 4 篇（1.7%）|
| 单篇耗时 | 中位 60.0s / 平均 61.1s / 最长 220.8s |
| 累计权利要求 | ~3500 条（中位 14 / 平均 14.6 / 最长 30）|
| 累计原子特征 | **7224** 个（中位 28 / 平均 30.2）|

### 4.2 9 类技术标签分布（239 篇）

| 标签 | 数量 |
|---|---|
| 其他 | 100 |
| 智能座舱与车联网 | 50 |
| 整车与车身底盘 | 44 |
| 充配电系统 | 23 |
| 智能驾驶 | 13 |
| 电驱系统 | 5 |
| 动力电池 | 3 |
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
- **现状**：每次调用都重新请求 ChatGPT Codex；模块二开发时如需重新抓取 `task_package` 会重新触发 LLM。
- **建议**：以 `(publication_no, prompt_hash, model)` 为 key 加缓存层，命中直接返回，提供 `--no-cache` 强制刷新。

### 🟡 5.2 LLM schema 校验失败不会自修复
- **现状**：`chat_json` 只对网络/限流类错误重试，碰到 schema 校验失败直接抛 `LLMOutputError`。
- **影响**：239 篇里没遇到，但属于潜在脆弱点。
- **建议**：把 `LLMOutputError` 也纳入 1 次重试，重提时附上"上一轮的错误信息 + 字段位置"作为 self-repair 提示。

### 🟡 5.3 PDF 选页规则用 marker 扫描，不够鲁棒
- **现状**：[`pdf.py:render_claim_pages`](../../fetcher/pdf.py) 用「权利要求书」+「说明书」关键词找页边界。
- **风险**：极少数 PDF 把「权利要求书」印在页眉每页都命中；或单页同时含权利要求结尾 + 说明书开头会被截断。本次 4 篇 PDF Vision 都没踩到。
- **建议**：改为定位「权利要求书」首次出现页 → 「说明书」/「附图说明」首次出现页 之间的 range 切片。

### 🟡 5.4 `pdf_url` 为空且有图片占位时直接报错
- **现状**：[`pipeline.py`](pipeline.py) 在 `has_claim_image_placeholders=True` 但 Google 没收录 PDF 时抛 `PatentFetchError`。
- **影响**：少数边角专利无法处理。
- **建议**：增加一个 fallback —— 在 prompt 里告知 LLM "HTML 含占位但 PDF 不可得，按 HTML 原样拆解并标注异常条目"，而非整体失败。

### 🟡 5.5 申请人 alias 字典只有 3 个 BYD 实体
- **现状**：[`google_patents.py:_CN_ASSIGNEE_ALIASES`](../../fetcher/google_patents.py) 硬编码。
- **缓解**：因为 `assigneeOriginal` 直接取中文已经覆盖绝大多数情况，alias 表实际很少触发。
- **建议**：等模块二在非 BYD 专利上遇到中文化失败时再补；不阻塞当前任务。

### 🟡 5.6 测试覆盖收敛
- **现状**：删除了 `test_decompose.py` / `test_claims_fetch_pool.py`，只保留 [`run_full_pool_decompose.py`](../../../../tests/decompose/run_full_pool_decompose.py) 的全量 E2E。
- **影响**：单元级回归（normalize_publication_no、HTML claim 抽取、申请人映射）不再有快速测试，全量 E2E 耗时长且烧 LLM 配额。
- **建议**：之后在 [`tests/decompose/`](../../../../tests/decompose/) 加一个 `test_unit.py`，把不依赖 LLM 的 fetcher / schema / normalize 单测补回来，给 CI 用。

### 🟡 5.7 错别字修正规则尚未在大样本上深度抽查
- **现状**：本次 239 篇全量跑里已加入「错别字保守修正」豁免规则（rule 1），但没有系统地比对 LLM 修正了哪些字。
- **建议**：写一个 diff 工具，把 `claim_text`（拆解后）与从 Google Patents 重新抓取的原始 HTML 文本做字符级 diff，列出所有差异，人工抽查是否都属于"明显错别字"范围。

### 🟡 5.8 if-else 二分边界仍偶有偏差
- **现状**：CN118629013B 权 17 类「距离≤阈值→匹配成功 / 距离>阈值→匹配失败」这种**同一布尔条件的二分**仍被拆为 2-3 条，未按规则 6 合并。
- **缓解**：示例 4 的"注意"段已说明并列条件可分开；模型在边界判断上偏保守，影响有限（每条仍可独立找证据）。
- **建议**：在示例 4 增补一条"同一阈值的两侧分支应合并"的对照例。

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

### 6.4 全量 239 篇端到端

```bash
python tests/decompose/run_full_pool_decompose.py
# 断点续跑：已存在 task_package.json 的专利自动跳过
# 配额自愈：触顶时 sleep 30 分钟后重试，最多 12 次
```

输出：
- `tests/decompose/outputs/<pub>/task_package.json` × 239
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
