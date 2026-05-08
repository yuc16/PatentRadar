# PatentRadar v1

> **专利侵权线索挖掘系统** — 输入中文专利公开号，输出围绕权利要求 1 的 Top5 疑似侵权竞品分析报告。

---

## 1. 项目目标

输入中文专利公开号（例 `CN107423660B`），系统自动完成：

1. 抓取并解析专利全文；**多模态 GPT-5.5 重建权利要求 1 含 LaTeX 公式的完整原文**；
2. 拆解权利要求 1 为 F1/F2/F3... 原子技术特征；
3. **三个搜索 Agent 并行**（DeepSeek / Kimi / GLM）从不同视角挖掘**中国大陆市场可见的竞品**；
4. 每个 Agent 自成闭环：找竞品 → 找证据 → 按特征匹配 → 硬规则过滤 → 输出 Top5；
5. **GPT-5.5 最终复核**：复核前自动补搜证据，跨候选合并去重（凭行业知识识别同义）、证据真实性校验、代码级重算分数与风险等级；
6. 输出结构化 Markdown 报告。

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
        candidate_pool.json
               ↓
┌─────────────────────────────┐
│ GPT-5.5 Final Reviewer       │
│  - 证据不足项代码侧补搜       │
│  - 合并去重（行业知识同义识别）│
│  - 证据真实性校验             │
│  - 代码级统一打分 + 风险等级   │
└──────────────┬──────────────┘
               ↓
        final_report.json
               ↓
┌─────────────────────────────┐
│ Markdown 报告                │
└──────────────┬──────────────┘
               ↓
   output/<pub_no>/final_report.md
```

---

## 3. 当前实现状态

| # | 功能项 | 状态 |
|---|---|---|
| 1 | 输入专利公开号 | ✅ |
| 2 | GPT-5.5 拆解权要 1（含 LaTeX 公式视觉重建） | ✅ |
| 3 | 生成统一任务包 | ✅ |
| 4 | 三个 Agent 并行检索 | ✅ |
| 5 | 每个 Agent 输出 Top5 | ✅ |
| 6 | 汇总最多 15 个候选 | ✅ |
| 7 | 候选去重（GPT-5.5 智能合并） | ✅ |
| 8 | GPT-5.5 最终复核（含代码侧补搜 / 重算校验） | ✅ |
| 9 | 输出最终 Top5 Markdown 报告 | ✅ |

**MVP 9/9 全部完成**。

额外实现了平衡证据模式：证据阶段按“规格参数 / 结构形态 / 算法流程 / 上市日期”等证据目标生成中英双语 query，一份规格书或产品页可同时支撑多个相关特征；不同目标会选择更合适的搜索源，缺口补搜才扩到更广的共享池；URL 会先规范化去重，并要求命中当前公司 / 产品 / 别名后才进入正文读取；首轮信号过弱的候选不做扩展补搜；二次候选搜索补足到 3 个有效候选或已有强候选即停止；高价值官网 / 产品页 / 文档中心才触发 Tavily Crawl；同一轮任务共享搜索、正文抽取和 crawl 缓存；最终复核会跳过 Agent 已搜过的 query，针对缺口目标补搜，并由代码补齐特征表、重算分数。

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
EXA_API_KEY=...      # 语义搜索 highlights + Contents 抽取
BRAVE_API_KEY=...    # 广域 Web + News（上市日期证据）
TAVILY_API_KEY=...   # search + extract + crawl
TAVILY_API_KEYS=...  # 可选，多 key 建议用英文逗号分隔；运行时自动轮换

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
REVIEWER_LLM_RETRY_ATTEMPTS=3           # 最终复核遇到限流/网络抖动时的重试次数
REVIEWER_LLM_RETRY_DELAY_SECONDS=60     # 最终复核重试基础等待秒数（第 n 次等待 n 倍）
CODEX_STREAM_TIMEOUT=420                # GPT-5.5 SSE 流单次读超时秒数
CODEX_JSON_RETRY_ATTEMPTS=3             # GPT-5.5 JSON 调用网络/限流重试次数
CODEX_JSON_RETRY_DELAY_SECONDS=30       # GPT-5.5 JSON 重试基础等待秒数
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
# 最终报告：output/$PUB/final_report.md（始终是最新一份）
# 工作流归档：output/$PUB/runs/<YYYYMMDD_HHMMSS>/  （一次工作流一个目录，4 份 log + final_report.md 都在里面）
#
# "工作流"由 tmp/$PUB/.current_run_dir 持久化追踪：
#   · 默认行为：4 个 CLI 命令依次跑，自动归并到同一目录
#   · PATENTRADAR_NEW_RUN=1 cmd ...   强制新建一个工作流目录
#   · rm tmp/$PUB/.current_run_dir   下次跑就自动新建
```

**Web 仪表盘**（实时观察四个 Agent 的日志流）：

```bash
# 任意终端启动一次（独立常驻，不影响 CLI 跑专利）
uv run patentradar web --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

工作方式：

- **自动锁定到最新一次 run**——页面打开后调 `/api/current-run` 找到 `output/` 下**最新的 log 文件**，无需手动选专利。
- 三状态机：
  - **NO RUN**：项目里还没跑过任何专利，提示等待 CLI 启动。
  - **LIVE**：当前 log 文件 mtime < 5 分钟（覆盖单次 LLM 调用最长等待），右上 LIVE 灯，SSE 增量推送，**不出回放按钮**。
  - **DONE**：log 停止写入，出现 ▶ 回放 + 60×/200×/600× 倍速进度条，**仅回放本次 run**。
- 4 列分别滚动 GPT-5.5 控制器 / DeepSeek / Kimi / GLM 的日志，按 `[agent]` tag 自动分流，URL 命中行可点击跳转。
- 右上 📦 Artifacts 抽屉**仅显示本次 run 的产物**——后端按 `since=<run_started_at>` 过滤产物 mtime，旧 run 的遗留产物显示为"✗ 本次 run 未生成"，不会误导。
- `find-competitors-all` / `review` 启动时会把 `task_package.json` 缓存中的拆解结果（GPT-5.5 给出的 F1~Fn + industry_tag）以 `DECOMPOSE CACHED` 行写进 log，方便追溯历史拆解。

详细实现见 [`web/`](web/) 目录与 [`src/patentradar/web/`](src/patentradar/web/)。

---

## 7. 目录结构

```
PatentRadar/
├── README.md                        # 本文件
├── pyproject.toml / uv.lock         # 依赖锁
├── .env.example / .env              # 配置模板 / 实际配置（git 忽略，优先于 shell 环境变量）
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
│       ├── candidate_pool.json      # 三 Agent Top 候选归并快照
│       ├── review_supplement_cache.json # 最终复核补搜缓存，可续跑
│       ├── final_report.json        # 阶段 4
│       └── .current_run_dir         # 持久化当前工作流的 RUN_DIR 路径（删了下次跑会自动新建）
│
├── output/                          # 最终用户产物（git 忽略）
│   └── <pub_no>/
│       ├── final_report.md          # 始终是最新一次 report 的副本（被覆盖）
│       └── runs/                    # 历次工作流归档
│           └── <YYYYMMDD_HHMMSS>/   # 一次工作流一个目录（首个命令的开始时间）
│               ├── decompose.log
│               ├── find-competitors-all.log
│               ├── review.log
│               ├── report.log
│               └── final_report.md  # 同次工作流跑出的 md 副本，跨工作流互不覆盖
│
├── web/                             # Web 仪表盘前端静态站点（暖色风 4 列）
│   ├── index.html                   # 单页主入口；自动锁定到最新 run，三状态机 NO RUN/LIVE/DONE
│   └── data/timeline.js             # /api/current-run + SSE 增量 + 产物按 since 过滤
│
└── src/patentradar/
    ├── cli.py                       # Typer CLI 入口
    ├── config.py                    # .env 加载 + 端点路由
    ├── schemas.py                   # 全流程 Pydantic schema
    ├── scoring.py                   # 硬规则 + 计分
    ├── evidence.py                  # 深度证据策略：分层、query、crawl 目标筛选
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
    │   └── pool.py                  # 多引擎并行 + URL 黑名单 + extract/contents/crawl
    │
    ├── reviewer/
    │   ├── reviewer.py              # 最终补搜 + GPT-5.5 复核 + 代码重算
    │   └── merger.py                # candidate_pool.json 合并快照
    │
    ├── report/
    │   └── markdown.py              # Markdown 报告渲染
    │
    ├── web/                         # Web 仪表盘后端（FastAPI + SSE）
    │   ├── server.py                # /api/patents · /events · /stream · /artifacts
    │   └── log_parser.py            # runs/*.log → {agent, kind, text, url, t}
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

### 8.2 三 Agent 视角差异化

| Agent | 模型 | 主搜索源 | 视角 |
|---|---|---|---|
| DeepSeek | deepseek-v4-pro | bocha + tavily | 中文公开资料 |
| Kimi | kimi-k2.6 | tavily + exa | 官方 / 长文 / PDF |
| GLM | glm-5.1 | exa + brave | 语义扩展 |

**所有 Agent 共同遵守一条硬规则**：候选必须是**中国大陆市场可见的产品**——CN 专利仅在中国大陆境内有禁止权。GLM 用英文/语义扩展是发现手段，但目标候选仍须有中国销售迹象（中国代理 / 中文资料 / 国内整机集成 / 京东淘宝在售等）。

### 8.3 单 Agent 工作流 S1~S10

```
S0  接收任务包
S1  生成候选发现 query (LLM, 默认最多 10 条; 不足时自动补调)
S2  调用主搜索源召回 hits
S3  建立粗候选池 (默认 ≤50，URL 黑名单源头过滤专利文献站)
S4  LLM 归一化 + 严苛筛选（无明确公司 / 专利文献站 / 无中国市场迹象 → 直接丢）
S5  保留重点候选（默认 8 个）
S6  对每个候选执行目标化证据补搜：
    - 按证据目标分组生成中英双语 query，而不是机械逐特征搜索
    - 规格书 / 产品页 / PDF 可同时支撑尺寸、参数、结构等多个相关特征
    - 按目标选择搜索源：Tavily 默认参与，规格类偏 Tavily + Brave + Exa，上市日期偏 Bocha + Tavily + Brave News，缺口 / 反证再扩到全搜索池
    - URL 去除跟踪参数、规范化去重，并过滤明显不含当前公司 / 产品 / 别名的结果
    - 正文读取：Tavily Extract → Exa Contents 兜底
    - 首轮特征判断后，只对“证据不足 / remaining gap / 缺 URL”的证据目标补搜
    - 首轮分数和命中特征都过低时跳过扩展补搜，避免低质量候选继续消耗搜索额度
    - 行业种子站可派生少量 site: query，用于召回规格页、经销商规格和 PDF 索引
    - 仅对官网 / 产品页 / 文档中心等高价值 URL 触发 Tavily Crawl
    - 证据按 Tier 1/2/3/4 分层后再交给 LLM，单候选默认读取前 5 个高价值 URL、最多 9 页证据；高明确度产品或高分缺口补搜会小幅放宽预算
    → ★ compactor 动态压缩 ★（按 ctx_window 预算，长文 LLM 摘要）
S7  LLM 把证据绑定到 F1/F2/F3 + 给出四档判断
S8  代码级补齐缺失特征 + 硬规则过滤
S9  按完整特征表重算分数 + 证据质量同分排序
S10 输出 Top5 JSON

如果首轮有效候选明显不足（默认少于 3 个），Agent 会生成新 query 并二次搜索候选池；二轮一旦补足 3 个有效候选就立即停止，仍不足时宁缺毋滥。
```

### 8.4 证据策略：目标分组 + 中英双语召回

系统默认先保证证据广度，再用证据目标分组控制重复调用。实现集中在 [`src/patentradar/evidence.py`](src/patentradar/evidence.py) 与 [`src/patentradar/search/pool.py`](src/patentradar/search/pool.py)：

- **证据目标分组**：系统会把相关特征合并成“规格/参数/手册”“结构/形态/连接”“算法/控制/流程”“上市/发布/量产日期”等目标。一份 datasheet、产品规格页或 PDF 可能同时支撑多个 F 项。
- **中英双语 query**：每个目标都会生成中文、英文和混合 PDF / datasheet / specification / technical document 方向；国内厂商也会查英文公开资料。
- **缺口补搜**：Agent 首轮判断后，只对仍为“证据不足”、有 remaining gap、或判断缺少 URL 的目标继续补搜。首轮信号过低的候选会止损，避免把明显弱相关候选扩成几十页证据。
- **行业种子站与行业 profile**：`data/cn_industry_sites/<tag>.json` 可放行业媒体、厂商官网、规格资料站和经销商站点，也可在 `evidence_profile` 中放该行业专属商品名、英文特征映射、规格页路径提示和补搜 query 模板。通用 `evidence.py` 不写入电池、半导体、汽车等专用词，避免污染其他领域搜索。
- **候选相关性过滤**：搜索命中的 URL 会去除 `utm_*` / `srsltid` 等跟踪参数后去重；正文读取前必须在 URL / title / snippet 中匹配当前公司、产品型号或别名。
- **搜索源选择**：证据阶段不再所有 query 都打满 Bocha / Exa / Brave / Tavily，而是按目标选择。规格 / datasheet 目标偏 Tavily + Brave + Exa；结构 / 算法 / 产品文档偏 Tavily + Exa + Brave；上市日期偏 Bocha + Tavily + Brave News，且只在候选缺上市日期或缺日期证据 URL 时触发；缺口或反证补搜才扩到全搜索池。任一搜索源失败或额度不足时，`pool.search` 会记录失败并继续使用其他搜索源返回结果。
- **Tavily 多 key 轮换**：`TAVILY_API_KEYS` 可配置多个 key；遇到额度、权限或限流错误时自动换下一个 key。`TAVILY_API_KEY` 仍可单独使用。
- **Exa snippet 策略**：Exa 搜索阶段默认请求 highlights 作为 snippet，优先使用高亮短文本；只有显式需要全文时才请求 text，正文读取仍由 Exa Contents 兜底。
- **正文抽取顺序**：Tavily Extract 优先，读不到正文时 Exa Contents 兜底。
- **正文预算**：单候选默认最多读取前 5 个高价值 URL、最多保留 9 页证据；产品型号足够明确时提升到 6 个 URL / 10 页，高分候选的缺口补搜最多 8 个 URL / 12 页；进入 LLM 前再由 compactor 摘要 / 截断长文。
- **运行级缓存**：`find-competitors-all` 的三个 Agent 和后续 `review` 复用同一个 `SearchSession` 缓存目录，搜索结果、正文抽取结果和 crawl 结果分别落到 `tmp/<pub_no>/search_cache.json`、`page_cache.json`、`crawl_cache.json`，避免并行 Agent 和复核阶段重复请求同一 query / URL。
- **来源分层**：官方网页、官方 PDF、产品手册、白皮书、年报、招股书、标准、认证资料为 Tier 1；行业报告 / 权威媒体 / 展会资料为 Tier 2；普通新闻 / 代理商 / 电商等为 Tier 3；自媒体 / 论坛 / 二手转载为低可靠线索。
- **Crawl 目标筛选**：Tavily Crawl 只深挖官网产品页、下载页、支持页、文档中心、SDK/开发者资料页，不爬新闻站、论坛、自媒体、电商或专利站。
- **证据-特征提示**：进入 LLM 的证据块会标注 `线索特征: F3, F5` 和来源 Tier，减少证据错配。
- **复核补搜去重**：Reviewer 会读取 Agent 已执行的 query，跳过重复 query，只对仍有缺口的证据目标补搜，并复用同一套 URL 规范化与候选相关性过滤。

### 8.5 上下文动态压缩 + LLM 摘要

每个 LLM 调用前根据 ``ctx_window``（从 `.env` 读，每个端点独立）算实际预算：

```
budget = ctx_window * COMPACTOR_BUDGET_RATIO - COMPACTOR_OUTPUT_RESERVE - prompt_overhead
```

- 整体 ≤ 预算 → 全量保留；
- 超出 → 对**单篇 token 数高的**长文调便宜 LLM (`COMPACTOR_LLM=agent3`) 做关键事实摘要（200~400 字，按"产品 / 公司 / 参数 / 结构 / 算法"5 维聚焦）；
- 仍超出 → 按 token 从大到小腰斩（保留首尾），最后才丢弃。

实现：[`src/patentradar/compactor.py`](src/patentradar/compactor.py)。

### 8.6 GPT-5.5 复核：先补搜，再合并去重

复核阶段先对 Agent 输出中"证据不足"、有 remaining gap、或缺少 URL 证据的高价值候选做一轮代码侧补搜。补搜会按证据目标选择搜索源，并跳过 Agent 阶段已经执行过的 query；新增 URL 同样需要通过公司 / 产品 / 别名相关性过滤，避免把无关长 PDF 塞进复核上下文。

候选同义合并不依赖代码层正则归一化——GPT-5.5 用**行业知识**自动识别同义：

```
"Cypress CYFP1-8080-FPG1"  ⇨  Infineon Technologies   (Cypress 已被 Infineon 收购)
"Fingerprint Cards (FPC)"  ⇨  Fingerprint Cards AB    (品牌缩写 + 多型号合并)
"汇顶科技 / Goodix"          ⇨  汇顶科技
```

复核还做：证据真实性校验、四档判断重判、风险等级。模型返回后，代码会再次补齐 F1/F2/F3... 全量特征表，按完整权利要求 1 重算分数，自动排除无明确公司 / 产品 / 公开证据 URL、存在"明确不满足"必要特征，或已知产品上市/发布/量产日期不晚于专利申请日的候选；无法确定上市日期时不会因日期原因排除。

### 8.7 四档判断 + 风险等级

| 判断 | 分数 |
|---|---:|
| 明确满足 | 1.0 |
| 可能满足（须有推理链） | 0.8 |
| 证据不足 | 0.3 |
| 明确不满足（须有反证） | 排除 |

候选总分 = 各特征分数之和 / 特征总数 × 100，对应风险：≥85 高度疑似落入 / 70~84 中度疑似 / 50~69 局部相似 / <50 弱相关。

代码层会强制执行三条兜底：

- LLM 漏返回的特征按"证据不足"补齐，避免用较少特征做分母导致高估；
- "明确满足 / 明确不满足"没有公开证据 URL 时降级为"证据不足"；
- "可能满足"缺少公开证据 URL 或推理链时降级为"证据不足"。

### 8.8 缓存策略

- **阶段 1 拆解结果**默认缓存（`task_package.json` 存在则跳过）
- **阶段 3** 每个 Agent 独立缓存（`agent_<n>.json` 存在则跳过该 Agent）
- **阶段 4** 默认缓存（`final_report.json` 存在则跳过）
- **阶段 5** 渲染瞬完，每次都重新生成
- **搜索会话缓存**：`tmp/<pub_no>/search_cache.json` / `page_cache.json` / `crawl_cache.json` 记录本专利运行中的搜索、正文读取和 crawl 结果；同一 query / URL 重跑时优先命中缓存，使用 `--force` 重跑阶段产物时缓存文件仍可复用，手动删除这些文件即可强制重新请求搜索 API。
- 全部命令支持 `--force` 反向开关

### 8.9 中国行业垂类专项检索（DeepSeek 视角增强）

通用搜索引擎对中文营销话术的召回有限，因此 DeepSeek Agent 上又叠了三层增强：

1. **行业宣传语扩展（拆解阶段）** — GPT-5.5 在权要拆解时同时给出每条特征的 `marketing_terms`（中文行业宣传语，例：把"电池单体在长度方向上沿厚度方向叠置" 翻成 "刀片电池 / 长方形方壳电芯 / CTP 无模组"），并打一个 `industry_tag`，固化到 `task_package.json`。**`industry_tag` 的合法取值由 [`data/cn_industry_sites/*.json`](data/cn_industry_sites/) 自动派生**——新增 / 删除领域只改这个目录，prompt 里的取值表和代码里的白名单都自动跟随。DeepSeek 视角 query 生成时优先用宣传语而不是工程术语。
2. **行业站点定向召回（候选发现阶段）** — 按 `industry_tag` 加载 [`data/cn_industry_sites/`](data/cn_industry_sites/) 下对应白名单（自动叠加 `general.json` 通用站点），把 LLM 已生成的最聚焦的前 1~2 条 query **包装成 `(query) (site:domain1 OR site:domain2 ...)`** 用 Bocha 单独召回。媒体/协会组与厂商官网组分两条 query，互不干扰。
3. **巨潮资讯证据补搜（证据收集阶段）** — 候选公司确定后，DeepSeek 自动用 `公司名 + 产品/型号` 查 [`巨潮资讯`](http://www.cninfo.com.cn/)（A 股 / 港股年报、招股书、公告全文）。返回的 PDF URL 直接进证据池，由 Exa Contents / Tavily Extract 兜底链抽正文。年报/招股书是上市企业最权威的产品技术披露源。

**调整白名单 / 行业 profile**：直接编辑 [`data/cn_industry_sites/<tag>.json`](data/cn_industry_sites/)，新增/删除 `sites[].domain` 即可；行业专属证据策略放在同文件的 `evidence_profile`，包括 `generic_terms`、`named_product_hints`、`spec_queries`、`feature_term_map` 等。**新增领域只需新建一个 `<tag>.json`**（必含 `industry_tag` / `label` / `prompt_description` / `sites`），系统会自动把它注入 GPT-5.5 拆解 prompt 的取值表和代码白名单——无需改 [`prompts/claim_decompose_system.md`](src/patentradar/prompts/claim_decompose_system.md) 或 [`patent/decomposer.py`](src/patentradar/patent/decomposer.py)。详情见 [`data/cn_industry_sites/README.md`](data/cn_industry_sites/README.md)。

`battery.json` 已放入若干电芯规格资料、经销商站点和电池专属 `evidence_profile` 作为试点；候选发现阶段仍只由 DeepSeek 启用行业站点路由（`AgentPerspective.cn_industry_routing=True`），证据阶段的高价值规格站 `site:` 召回和行业专属 query / 翻译映射会对三个 Agent 生效。

### 8.10 日志与可追溯性

每次 CLI 运行的**完整日志**（含 logger.info 的 S1~S10 阶段输出 + console.print 镜像）自动写到：

```
output/<pub_no>/runs/<YYYYmmdd_HHMMSS>_<cmd>.log
```

包含：每条 query 的命中数 + 来源、每个候选的特征判断结果、compactor 压缩统计、复核备注。

更细的排查点也会进入同一个日志文件：Agent 当前阶段、每次 LLM 调用的 START/DONE 和耗时、每个搜索引擎的 START/HIT/KEEP/DUP/SKIP/FAIL、低相关 URL 过滤、URL 抽取与 crawl 结果、最终复核补搜的每条 query 和新增 URL、补搜缓存命中、GPT-5.5 复核重试记录。

最终复核补搜会写入 `tmp/<pub_no>/review_supplement_cache.json`。如果补搜完成后最终模型调用被限流，重新执行 `review` 会直接复用缓存，继续进入最终复核，不会重复跑完整补搜。

---

## 9. 已知限制

| 限制 | 说明 | 改进方向 |
|---|---|---|
| 仅支持中文专利 (CN) | Google Patents 中文页 + 中文权要文本 | 扩展 US/EP 需重写权要抽取逻辑 |
| 仅独立权利要求 1 | 不分析从属权利要求 / 等同特征 | 后续可扩展从属权利要求、等同特征和 FTO 分析 |
| 海外候选地域过滤靠 prompt + 证据 | candidate_filter 阶段排除无中国销售迹象的海外候选；DeepSeek 已叠加行业站点定向 + 巨潮资讯 | 行业白名单需人工维护；新增领域只需新建 `<tag>.json` 即可（prompt 取值表和代码白名单自动跟随） |
| 最终补搜仍有上下文上限 | 复核前默认最多处理 15 个候选、每候选最多 4 个缺口特征；进入 LLM 前仍会分层和压缩 | 后续可把证据 appendix 独立落盘 |
| 摘要 LLM 与主 Agent 同源 | 当前 compactor 默认用 deepseek，与 deepseek_agent 共账号 | 可换为更便宜的独立模型 |

---

## 10. 法律免责声明

> 本系统输出**仅基于公开资料进行专利侵权线索辅助分析**，不构成法律意见或正式侵权结论。
> 所有"可能满足"判断需经人工复核。最终侵权判断需由专利代理人 / 律师 / 司法鉴定机构作出。

---

## 11. 致谢

- 模型：GPT-5.5（OpenAI Codex）、deepseek-v4-pro、kimi-k2.6、glm-5.1（aihubmix 中转）。
- 搜索：Bocha、Exa、Brave Web / News、Tavily。
- 数据源：Google Patents 公开数据。
