# PatentRadar v1

> **专利侵权线索挖掘系统** — 输入中文专利公开号，输出围绕权利要求 1 的 Top5 疑似侵权竞品分析报告（PRD §14）。

参考产品需求：[`专利侵权线索挖掘系统.md`](专利侵权线索挖掘系统.md)（PRD v1.0）

---

## 1. 项目目标

输入中文专利公开号（例 `CN107423660B`），系统自动完成：

1. 抓取并解析专利全文；**多模态 GPT-5.5 重建权利要求 1 含 LaTeX 公式的完整原文**；
2. 拆解权利要求 1 为 F1/F2/F3... 原子技术特征（PRD §10）；
3. **三个搜索 Agent 并行**（DeepSeek / Kimi / GLM）从不同视角挖掘**中国大陆市场可见的竞品**；
4. 每个 Agent 自成闭环：找竞品 → 找证据 → 按特征匹配 → 硬规则过滤 → 输出 Top5；
5. **GPT-5.5 最终复核**：跨候选合并去重（凭行业知识识别同义）、证据真实性校验、重打分、风险等级判定；
6. 输出 PRD §14 结构的 Markdown 报告。

定位：**专利竞品侵权线索挖掘与证据整理辅助工具**，不构成法律意见或正式侵权结论。

---

## 2. 系统架构

```
┌─────────────────────────────┐
│ Patent Input (CN专利公开号)  │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ GPT-5.5 多模态拆解            │
│  - Google Patents 抓取        │
│  - 公式残缺检测               │
│  - 视觉重建权要 + LaTeX 公式  │
└──────────────┬──────────────┘
               ↓
        task_package.json
               ↓
┌─────────────────────────────┐
│ Multi Search Agents (并行)   │
│  ┌───────────┬─────────────┐ │
│  │ DeepSeek  │ 中文公开资料  │ │
│  │ Kimi      │ 官方/长文资料 │ │
│  │ GLM       │ 语义扩展     │ │
│  └───────────┴─────────────┘ │
│  S1~S10 完整闭环             │
│  ★ 中国市场过滤前置 ★         │
│  ★ 上下文动态压缩 ★          │
└──────────────┬──────────────┘
               ↓
   agent_<deepseek|kimi|glm>.json × 3
               ↓
┌─────────────────────────────┐
│ GPT-5.5 Final Reviewer       │
│  - 合并去重（行业知识同义识别）│
│  - 证据真实性校验             │
│  - 统一打分 + 风险等级        │
└──────────────┬──────────────┘
               ↓
        final_report.json
               ↓
┌─────────────────────────────┐
│ Markdown 报告 (PRD §14)      │
└──────────────┬──────────────┘
               ↓
   output/<pub_no>/final_report.md
```

---

## 3. 当前实现状态（PRD §18.1 MVP 9 项 ✅）

| # | PRD MVP 项 | 状态 |
|---|---|---|
| 1 | 输入专利公开号 | ✅ |
| 2 | GPT-5.5 拆解权要 1（含 LaTeX 公式视觉重建） | ✅ |
| 3 | 生成统一任务包 | ✅ |
| 4 | 三个 Agent 并行检索 | ✅ |
| 5 | 每个 Agent 输出 Top5 | ✅ |
| 6 | 汇总最多 15 个候选 | ✅ |
| 7 | 候选去重（GPT-5.5 智能合并） | ✅ |
| 8 | GPT-5.5 最终复核 | ✅ |
| 9 | 输出最终 Top5 Markdown 报告 | ✅ |

**MVP 9/9 全部完成**。

---

## 4. 安装

```bash
cd PatentRadar
uv sync                       # 自动创建 venv + 安装依赖（Python 3.14+）
cp .env.example .env          # 复制配置模板
# vim .env，填入 key
```

> **GPT-5.5 OAuth 准备**：在终端运行 `codex login`，按提示登录 ChatGPT Plus/Pro 账号，会生成 `~/.codex/auth.json`。系统直接读这个文件做 OAuth；`.env` 中 REVIEWER_API_KEY / REVIEWER_BASE_URL 仅占位，不读。

---

## 5. 配置（`.env`）

```bash
# ---------- 主控 / 最终复核 LLM (GPT-5.5) ----------
REVIEWER_API_KEY=chatgpt-oauth          # 占位（实际走 ~/.codex/auth.json）
REVIEWER_BASE_URL=chatgpt://codex
REVIEWER_MODEL=gpt-5.5
REVIEWER_REASONING_EFFORT=medium        # low | medium | high
DECOMPOSER_REASONING_EFFORT=medium      # 阶段 1 拆解推理强度
REVIEWER_CONTEXT_WINDOW=400000          # 上下文窗口（tokens）

# ---------- 三个搜索 Agent（OpenAI 兼容协议）----------
SEARCH_AGENT_1_API_KEY=...              # GLM - 语义扩展视角
SEARCH_AGENT_1_BASE_URL=https://aihubmix.com/v1
SEARCH_AGENT_1_MODEL=glm-5.1
SEARCH_AGENT_1_CONTEXT_WINDOW=128000

SEARCH_AGENT_2_API_KEY=...              # Kimi - 官方/长文视角
SEARCH_AGENT_2_BASE_URL=https://aihubmix.com/v1
SEARCH_AGENT_2_MODEL=kimi-k2.6
SEARCH_AGENT_2_CONTEXT_WINDOW=200000

SEARCH_AGENT_3_API_KEY=...              # DeepSeek - 中文公开视角
SEARCH_AGENT_3_BASE_URL=https://aihubmix.com/v1
SEARCH_AGENT_3_MODEL=deepseek-v4-pro
SEARCH_AGENT_3_CONTEXT_WINDOW=128000

# ---------- 4 个搜索 API ----------
BOCHA_API_KEY=...    # 中文 Web / 新闻 / 企业（也用于"行业站点定向"召回）
EXA_API_KEY=...      # 语义搜索 + Contents 抽取
BRAVE_API_KEY=...    # 广域 Web
TAVILY_API_KEY=...   # search + extract + crawl

# ---------- 巨潮资讯（cninfo）----------
# 无需配置 key。DeepSeek Agent 在证据补搜阶段自动用候选公司名查公告 / 年报。

# ---------- 运行参数 ----------
DECOMPOSER_LLM=reviewer                 # reviewer | agent1/2/3
PATENT_FETCH_TIMEOUT=30
LLM_TIMEOUT=120
AGENT_LLM_TIMEOUT=240
COMPACTOR_BUDGET_RATIO=0.7              # 上下文预算 = ctx_window * 此比例 - output_reserve
COMPACTOR_OUTPUT_RESERVE=4096
COMPACTOR_LLM=agent3                    # 长文摘要用的便宜 LLM 端点
```

---

## 6. CLI 使用

完整 5 命令：

```bash
PUB=CN107423660B

uv run patentradar decompose $PUB                # 阶段 1
uv run patentradar find-competitors-all $PUB     # 阶段 3（默认缓存，--force 重跑）
uv run patentradar review $PUB                   # 阶段 4（默认缓存）
uv run patentradar report $PUB                   # 阶段 5

# 批量阶段 1
uv run patentradar decompose-batch data/候选专利清单.xlsx

# 调试用：单 Agent
uv run patentradar find-competitors $PUB --agent deepseek
```

**通用开关**：

- `-v` / `-vv`：日志级别（INFO / DEBUG）
- `--force`：强制重跑（默认 `agent_*.json` / `final_report.json` 已存在则跳过）
- `--reasoning low|medium|high`：覆盖 `.env` 的推理强度
- `--out PATH`：自定义输出目录

**一条龙**（专利号 → 报告）：

```bash
PUB=CN107423660B
uv run patentradar decompose $PUB \
  && uv run patentradar find-competitors-all $PUB \
  && uv run patentradar review $PUB \
  && uv run patentradar report $PUB
# 最终报告：output/$PUB/final_report.md
# 运行日志：output/$PUB/runs/<TS>_<cmd>.log（包括 stdout 全镜像）
```

---

## 7. 目录结构

```
PatentRadar/
├── README.md                        # 本文件
├── 专利侵权线索挖掘系统.md           # PRD v1.0
├── pyproject.toml / uv.lock         # 依赖锁
├── .env.example / .env              # 配置模板 / 实际配置（git 忽略）
│
├── data/                            # 用户输入
│   ├── 候选专利清单.xlsx
│   └── cn_industry_sites/           # 中国行业媒体白名单（按领域分组，可手动调整）
│       ├── README.md
│       ├── general.json             # 通用国内财经 / 行业 / 政府站点（始终附加）
│       ├── battery.json             # 动力电池 / 储能
│       ├── semiconductor.json       # 半导体 / IC 封装 / 传感器
│       ├── automotive.json          # 整车 / 汽车电子 / 智驾
│       └── display.json             # 显示面板 / 触控
│
├── tmp/                             # 中间产物缓存（git 忽略）
│   └── <pub_no>/
│       ├── task_package.json        # 阶段 1
│       ├── agent_deepseek.json      # 阶段 3
│       ├── agent_kimi.json
│       ├── agent_glm.json
│       ├── agent_outputs.json       # 三 Agent 合并视图
│       └── final_report.json        # 阶段 4
│
├── output/                          # 最终用户产物（git 忽略）
│   └── <pub_no>/
│       ├── final_report.md          # 阶段 5（PRD §14）
│       └── runs/
│           └── <TS>_<cmd>.log       # 每次 CLI 运行日志（含 stdout 镜像）
│
└── src/patentradar/
    ├── cli.py                       # Typer CLI 入口
    ├── config.py                    # .env 加载 + 端点路由
    ├── schemas.py                   # 全流程 Pydantic schema
    ├── scoring.py                   # 硬规则 + 计分（PRD §9/§10）
    ├── compactor.py                 # 上下文动态压缩 + LLM 摘要
    │
    ├── llm/
    │   ├── client.py                # OpenAI 兼容客户端
    │   └── codex.py                 # GPT-5.5 OAuth 多模态客户端
    │
    ├── patent/
    │   ├── fetcher.py               # Google Patents 抓取 + 公式残缺检测
    │   ├── vision.py                # PDF 权要书页 PNG 渲染
    │   └── decomposer.py            # 按需视觉拆解（GPT-5.5）
    │
    ├── agents/
    │   ├── base.py                  # SearchAgent (S1~S10) + compactor 集成
    │   └── perspectives.py          # 三视角配置
    │
    ├── search/
    │   ├── base.py                  # SearchHit / ExtractedPage
    │   ├── bocha.py / exa.py / brave.py / tavily.py
    │   ├── cninfo.py                # 巨潮资讯全文检索（无需 key，DeepSeek 证据补搜用）
    │   ├── cn_industry.py           # 行业白名单加载 + site: 限定 query 拼接
    │   └── pool.py                  # 多引擎并行 + URL 黑名单 + reader 兜底链
    │
    ├── reviewer/
    │   ├── reviewer.py              # GPT-5.5 复核（合并 + 重打分）
    │   └── merger.py                # 旧版代码合并器（已废弃，保留兼容）
    │
    ├── report/
    │   └── markdown.py              # PRD §14 渲染
    │
    └── prompts/                     # 所有长 prompt 单独维护
        ├── claim_decompose_*.md
        ├── agent_query_gen_*.md      # 3 视角 query
        ├── agent_candidate_filter*.md
        ├── agent_feature_match*.md
        └── reviewer_*.md
```

---

## 8. 核心设计决策

### 8.1 GPT-5.5 多模态：权要拆解 + 公式 LaTeX 重建

GPT-5.5 是**多模态模型**，本系统已经使用其视觉能力：

- **场景 1（已用）**：Google Patents 把权要中的公式渲染为 `<span class="patent-image-not-available">`（HTML 与 PDF 文字层都丢失符号）。fetcher 检测到此标志后，触发 `vision.py` 下载官方 PDF + pymupdf 渲染权要书页为 PNG，交给 GPT-5.5 一次性产出含 `$$X'=X-a*X_j$$` 等 LaTeX 的完整权要 + 拆解 JSON。
- **按需视觉**：无公式专利走纯文本路径（省 vision token），有公式才下载 PDF 渲染。258 篇全量验证：仅约 0.4% 触发视觉路径。
- **未来可扩展**：让 GPT-5.5 看候选产品的拆解图、PCB 照片、结构示意图等，做更深入的特征匹配（v1 暂未启用，留作 v2 方向）。

### 8.2 三 Agent 视角差异化（PRD §6.3）

| Agent | 模型 | 主搜索源 | 视角 |
|---|---|---|---|
| DeepSeek | deepseek-v4-pro | bocha + tavily | 中文公开资料 |
| Kimi | kimi-k2.6 | tavily + exa | 官方 / 长文 / PDF |
| GLM | glm-5.1 | exa + brave | 语义扩展 |

**所有 Agent 共同遵守一条硬规则**：候选必须是**中国大陆市场可见的产品**——CN 专利仅在中国大陆境内有禁止权。GLM 用英文/语义扩展是发现手段，但目标候选仍须有中国销售迹象（中国代理 / 中文资料 / 国内整机集成 / 京东淘宝在售等）。

### 8.3 单 Agent 工作流 S1~S10（PRD §8.1）

```
S0  接收任务包
S1  生成候选发现 query (LLM, 6~10 条; 不足时自动补调)
S2  调用主搜索源召回 hits
S3  建立粗候选池 (≤40，URL 黑名单源头过滤专利文献站)
S4  LLM 归一化 + 严苛筛选（无明确公司 / 专利文献站 / 无中国市场迹象 → 直接丢）
S5  保留重点候选 8~12 个
S6  对每个候选共享证据池补搜 + 抽正文（tavily_extract → exa_contents 兜底）
    → ★ compactor 动态压缩 ★（按 ctx_window 预算，长文 LLM 摘要）
S7  LLM 把证据绑定到 F1/F2/F3 + 给出四档判断
S8  硬规则过滤（PRD §9）
S9  极简计分排序（PRD §10.3）
S10 输出 Top5 JSON
```

### 8.4 上下文动态压缩 + LLM 摘要

每个 LLM 调用前根据 ``ctx_window``（从 `.env` 读，每个端点独立）算实际预算：

```
budget = ctx_window * COMPACTOR_BUDGET_RATIO - COMPACTOR_OUTPUT_RESERVE - prompt_overhead
```

- 整体 ≤ 预算 → 全量保留；
- 超出 → 对**单篇 token 数高的**长文调便宜 LLM (`COMPACTOR_LLM=agent3`) 做关键事实摘要（200~400 字，按"产品 / 公司 / 参数 / 结构 / 算法"5 维聚焦）；
- 仍超出 → 按 token 从大到小腰斩（保留首尾），最后才丢弃。

实现：[`src/patentradar/compactor.py`](src/patentradar/compactor.py)。

### 8.5 GPT-5.5 复核：合并去重交给模型

不依赖代码层正则归一化——GPT-5.5 用**行业知识**自动识别同义：

```
"Cypress CYFP1-8080-FPG1"  ⇨  Infineon Technologies   (Cypress 已被 Infineon 收购)
"Fingerprint Cards (FPC)"  ⇨  Fingerprint Cards AB    (品牌缩写 + 多型号合并)
"汇顶科技 / Goodix"          ⇨  汇顶科技
```

复核还做：证据真实性校验、四档判断重判、风险等级（PRD §15）。地域性已经由 Agent 阶段过滤前置，复核不再重复判定。

### 8.6 四档判断 + 风险等级（PRD §10 / §15）

| 判断 | 分数 |
|---|---:|
| 明确满足 | 1.0 |
| 可能满足（须有推理链） | 0.8 |
| 证据不足 | 0.3 |
| 明确不满足（须有反证） | 排除 |

候选总分 = 各特征分数之和 / 特征总数 × 100，对应风险：≥85 高度疑似落入 / 70~84 中度疑似 / 50~69 局部相似 / <50 弱相关。

### 8.7 缓存策略

- **阶段 1 拆解结果**默认缓存（`task_package.json` 存在则跳过）
- **阶段 3** 每个 Agent 独立缓存（`agent_<n>.json` 存在则跳过该 Agent）
- **阶段 4** 默认缓存（`final_report.json` 存在则跳过）
- **阶段 5** 渲染瞬完，每次都重新生成
- 全部命令支持 `--force` 反向开关

### 8.8 中国行业垂类专项检索（DeepSeek 视角增强）

通用搜索引擎对中文营销话术的召回有限，因此 DeepSeek Agent 上又叠了三层增强：

1. **行业宣传语扩展（拆解阶段）** — GPT-5.5 在权要拆解时同时给出每条特征的 `marketing_terms`（中文行业宣传语，例：把"电池单体在长度方向上沿厚度方向叠置" 翻成 "刀片电池 / 长方形方壳电芯 / CTP 无模组"），并打一个 `industry_tag ∈ {battery, semiconductor, automotive, display, general}`，固化到 `task_package.json`。DeepSeek 视角 query 生成时优先用宣传语而不是工程术语。
2. **行业站点定向召回（候选发现阶段）** — 按 `industry_tag` 加载 [`data/cn_industry_sites/`](data/cn_industry_sites/) 下对应白名单（自动叠加 `general.json` 通用站点），把 LLM 已生成的最聚焦的前 1~2 条 query **包装成 `(query) (site:domain1 OR site:domain2 ...)`** 用 Bocha 单独召回。媒体/协会组与厂商官网组分两条 query，互不干扰。
3. **巨潮资讯证据补搜（证据收集阶段）** — 候选公司确定后，DeepSeek 自动用 `公司名 + 产品/型号` 查 [`巨潮资讯`](http://www.cninfo.com.cn/)（A 股 / 港股年报、招股书、公告全文）。返回的 PDF URL 直接进证据池，由 Tavily Extract 抽正文。年报/招股书是上市企业最权威的产品技术披露源。

**调整白名单**：直接编辑 [`data/cn_industry_sites/<tag>.json`](data/cn_industry_sites/)，新增/删除 `domain` 即可。新增领域只需新建 `<tag>.json` 并在 [`prompts/claim_decompose_system.md`](src/patentradar/prompts/claim_decompose_system.md) 的 industry_tag 枚举里加上同名 tag，否则 LLM 不会用。

仅 DeepSeek 视角启用此路由（`AgentPerspective.cn_industry_routing=True`）；Kimi / GLM 不变，保持视角差异。

### 8.9 日志与可追溯性

每次 CLI 运行的**完整日志**（含 logger.info 的 S1~S10 阶段输出 + console.print 镜像）自动写到：

```
output/<pub_no>/runs/<YYYYmmdd_HHMMSS>_<cmd>.log
```

包含：每条 query 的命中数 + 来源、每个候选的特征判断结果、compactor 压缩统计、复核备注。

---

## 9. 已知限制

| 限制 | 说明 | 改进方向 |
|---|---|---|
| 仅支持中文专利 (CN) | Google Patents 中文页 + 中文权要文本 | 扩展 US/EP 需重写权要抽取逻辑 |
| 仅独立权利要求 1 | 不分析从属权利要求 / 等同特征 | PRD §2.2 明确为 v1 非目标 |
| 海外候选地域过滤靠 prompt + 证据 | candidate_filter 阶段排除无中国销售迹象的海外候选；DeepSeek 已叠加行业站点定向 + 巨潮资讯（§8.8） | 行业白名单需人工维护；新增领域要同步改拆解 prompt 的 industry_tag 枚举 |
| 摘要 LLM 与主 Agent 同源 | 当前 compactor 默认用 deepseek，与 deepseek_agent 共账号 | 可换为更便宜的独立模型 |

---

## 10. 法律免责声明

> 本系统输出**仅基于公开资料进行专利侵权线索辅助分析**，不构成法律意见或正式侵权结论。
> 所有"可能满足"判断需经人工复核。最终侵权判断需由专利代理人 / 律师 / 司法鉴定机构作出。

---

## 11. 致谢

- 系统架构源自项目 PRD v1.0（《专利侵权线索挖掘系统》）。
- 模型：GPT-5.5（OpenAI Codex）、deepseek-v4-pro、kimi-k2.6、glm-5.1（aihubmix 中转）。
- 搜索：Bocha、Exa、Brave、Tavily。
- 数据源：Google Patents 公开数据。
