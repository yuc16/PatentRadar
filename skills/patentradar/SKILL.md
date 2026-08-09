---
name: patentradar
description: 专利侵权竞品分析 skill。输入专利公开号（CN/US/EP/JP 等），输出可人工复核的 markdown 竞品分析报告。工作流：拆解权利要求 → 搜索市场竞品 → 抓证据（含图像）→ 全部权利要求逐特征对比 → 生成报告。触发词：专利侵权分析、专利竞品、claim chart、专利公开号、CN/US/EP/JP 专利号、专利对比、技术特征对比、专利保护范围、侵权风险评估。不适用：专利申请文书撰写、专利无效宣告、知识产权法律咨询、专利诉讼策略。
---

# PatentRadar 专利侵权竞品分析

## ⛔ 输入门禁（先于一切执行）

本 skill **只接受明确、完整的专利公开号/授权公告号**（下文统称 `PUBLICATION_NO`）。`PUBLICATION_NO` 必须包含国家/地区代码、文献号和文献种类代码（kind code），例如 `CN114512759A`、`CN114512759B`、`US10000000B2`、`EP1234567A1`。如果用户给出的 URL 中明确包含完整 `PUBLICATION_NO`，可以抽取后继续。

如果用户输入的是专利申请号、申请序列号、缺少 kind code 的号码，或任何无法唯一确定具体公开/公告文献的标识：

1. **立即停止执行**：不要联网解析对应公开号，不要猜测或默认选择 A/B 版本，不要创建输出目录，不要 spawn subagent。
2. 向用户说明：同一专利申请可能在不同程序阶段对应多个公开/公告文献号；申请文件在审查过程中可能修改，因此不同文献的权利要求文本可能不同。竞品侵权分析必须锁定具体文献版本。
3. 要求用户提供希望分析的完整专利公开号/授权公告号后再继续。

用户输入专利申请号时，优先使用以下回复模板：

> 你提供的是专利申请号，不是可唯一锁定权利要求版本的完整专利公开号/授权公告号。同一申请可能在不同程序阶段对应多个公开/公告文献号，且权利要求文本可能不同。请提供你希望分析的完整文献号（须含国家代码和 kind code，例如 `CN114512759A` 或 `CN114512759B`）。

只有输入通过本门禁后，才执行下方授权与工作流。

## ⚙️ 执行授权（必读，先于一切）

本 skill **必须以 4 个独立 subagent 串行执行**（decompose → competitor_search → full_claim_chart → report），subagent 之间通过 JSON 文件传递数据。

**用户已在本 skill 中预先授权你自由派生 subagent，不需要在会话里再次征求确认。** 看到本段就视为授权生效，直接按"## 架构"和"## 工作流"开始 spawn。

**严禁降级执行**：
- ❌ 不要因为"没有用户明确授权"就退回主对话单轮直答
- ❌ 不要把 4 个模块合并到一次 LLM 调用里
- ❌ 不要由主 agent 自己抓页面 / 看图 / 写报告内容
- ✅ 如果你判断当前环境**真的没法 spawn subagent**（比如 Task tool 不可用），立即**停下来报告原因**让用户决定，而不是自作主张降级单轮直答 —— 降级会让证据搜索深度大幅缩水，违反"## 🎯 核心总目标"。

## 🎯 核心总目标（全流程牢记）

**从市场公开渠道找出落入本专利权 1 保护范围的潜在竞品产品，用可追溯的证据（公开 URL + 引文 + 图像）逐特征对比，输出一份能让律师/工程师直接复核的 claim chart 报告，并对仍有缺口的特征明确"还缺什么、下一步可以去哪找"。**

**理想的产出**：找到一篇甚至多篇 `total_score ≥ 80`（侵权风险阈值）的竞品 —— 这意味着客户拿到报告后能立刻拍板"这家可能在侵权，可以发律师函/起诉了"。如果客观上真存在侵权竞品，**搜不到就是失职**；但如果确实没有相关侵权的竞品，也**不要靠放宽评分标准凑高分**。

判断质量的 3 把尺子（任一不达标都算没做到位）：

1. **每个判定都可追溯**：`明确满足` 必须有公开 URL 字面/数值证据（≥ 1 独立 host）；`可能满足` 必须给严谨推理链；`证据不足` / `明确不满足` 不能凭印象拍脑袋
2. **数学约束类必须现场算到数值**（D/V、S/E、L/S 等），不接受"满足公式约束"这种结论性话术
3. **证据缺口必须可执行**：权 1 中所有非"明确满足"的 feature 都必须给出 evidence_gap_brief，让人工拿着它就能去具体网站找具体证据，不要造空泛的"需进一步搜索"

**搜索深度与严格评分不矛盾**：
- 搜得**全**（多语言 query / 垂类站点 / 拆解视频 / 维修手册 / 专利文献 / 规格 PDF / 产品图 / 电路图）是为了**别错过真侵权竞品**
- 评分**严**（不自我宽松、有 ≥1 独立 host 才给"明确满足"、有严谨推理链才给”可能满足“）是为了**别给假高分**
- 两者一起做才能稳定挖出真侵权候选

每个 subagent 在执行细节决策时都应**先问自己**："这一步对达成上述目标有帮助吗？"——避免被局部规则牵着走、忘了大目标。

## 何时使用
用户给出**专利公开号**（CN/US/EP/JP 等）并要求做竞品分析 / 侵权风险评估 / claim chart 对比。典型输入：

- "分析 CN114512759B 的市场竞品"
- "帮我跑下 US10000000B2 的侵权风险"
- "对比这个专利和现有产品：[公开号]"


## 架构

主 agent（你）按顺序 spawn **4 个 subagent**，每个 subagent 独立完成一个模块，subagent 之间通过 JSON 文件传递数据。

```
用户输入专利号 → 主 agent（本 SKILL.md）
                  │
                  ├─ spawn subagent 1 → module_1/task_package.json
                  ├─ spawn subagent 2 → module_2/top_competitors.json
                  ├─ spawn subagent 3 → module_3/full_claim_chart.json
                  └─ spawn subagent 4 → module_4/report.md
```

每个 subagent 的完整 prompt 在 `agents/`。

## 工作流

### 步骤 0：准备

先执行“输入门禁”，确认用户给出的是带国家/地区代码和 kind code 的完整专利公开号/授权公告号（如 `CN114512759B`）。未通过时立即停止并要求用户更正；禁止自行解析、补全或选择文献版本。

确定输出目录：默认 `./patentradar_output/<PUBLICATION_NO>/`，或用户指定的目录。

创建子目录：
```
<output_dir>/
├── module_1/
├── module_2/
├── module_3/
└── module_4/
```

### 步骤 1：spawn subagent — 拆解权利要求

用 Task tool spawn `general-purpose` subagent，prompt 加载 `agents/decompose.md` + 用户的专利号。

**期望输出**：`<output_dir>/module_1/task_package.json`，符合 `schemas/task_package.md` 的结构。

跑完后**读这个 JSON 验证**：
- `claims` 数组非空
- 主题前序作为首条 feature（如 `C1-F1: 一种 XX 系统`）

### 步骤 2：spawn subagent — 竞品搜索 + 权 1 判定

用 Task tool spawn subagent，prompt 加载 `agents/competitor_search.md` + module_1 输出文件路径。

**期望输出**：`<output_dir>/module_2/top_competitors.json`，符合 `schemas/top_competitor_report.md`。

跑完后验证：
- `top_competitors` 数组，每家公司唯一（同公司去重已做）
- 每个候选有完整权 1 feature 对比 + total_score

### 步骤 3：spawn subagent — 全部权利要求扩展

用 Task tool spawn subagent，prompt 加载 `agents/full_claim_chart.md` + module_1 + module_2 输出文件路径。

**期望输出**：`<output_dir>/module_3/full_claim_chart.json`，符合 `schemas/full_claim_chart_report.md`。

跑完后验证：
- 每个 TOP 候选有全部权利要求的逐特征对比
- 权 1 中 status ∈ {可能满足, 证据不足} 的特征**都填了 `evidence_gap_brief`**

### 步骤 4：spawn subagent — 生成报告（markdown + PDF）

用 Task tool spawn subagent，prompt 加载 `agents/report.md` + module_1 + module_3 输出文件路径。

**期望输出**：
- `<output_dir>/module_4/report.md`
- `<output_dir>/module_4/report.pdf`（subagent 内部用 WeasyPrint 渲染；若系统库不齐导致渲染失败，允许只有 md）

### 步骤 5：交付

打印 markdown + PDF 两个路径给用户。同时给一个简短摘要：最高分竞品 + total_score + 是否触发 ≥80 风险阈值 + 失效候选数。

## 主 agent 的职责（要做什么 / 不要做什么）

**要做**：
- 按顺序 spawn 4 个 subagent，每次传清楚 prompt 文件路径 + 输入 JSON 路径 + 输出 JSON 路径
- **每个 subagent 跑完后，主 agent 必须跑 JSON Schema 校验**（用 `schemas/validate.py`，见下方"校验机制"段）；校验失败时**把错误清单透传给该 subagent**，让它修正后重交
- **任一 subagent 都有权随时回查权利要求原文**：如果对 task_package 中的 `claim_text` / `feature_text` 拆解有疑问，可访问 `patent.google_patents_url` 或 `patent.pdf_url` 复核原文（已写进每个 agent prompt 的"能力说明"段）

**不要做**：
- 主 agent 不要自己抓页面、不要自己看图、不要自己写报告内容 —— 全部由 subagent 干
- 不要把 4 个模块合并到一次调用（每个模块用独立 subagent 隔离上下文）

## 校验机制（每个模块跑完都要做）

每个 subagent 跑完后，**主 agent 必须用 `schemas/validate.py` 跑 JSON Schema 校验**，把结果反馈给 subagent（成功就走下一步；失败就把错误清单透传回去让它修正）。

```bash
# 模块一跑完后
python skills/patentradar/schemas/validate.py task_package <output_dir>/module_1/task_package.json

# 模块二跑完后
python skills/patentradar/schemas/validate.py top_competitor_report <output_dir>/module_2/top_competitors.json

# 模块三跑完后
python skills/patentradar/schemas/validate.py full_claim_chart_report <output_dir>/module_3/full_claim_chart.json
```

返回：
- **exit 0** + stdout `OK <data_path>` → 通过，进下一模块
- **exit 1** + stdout 错误清单（`[<json_path>] <message>` 每行一条）→ 失败
  - 主 agent 把这份错误清单**原样作为消息**发回该 subagent："你的输出 schema 校验失败，请按以下错误列表修正后重交：<错误清单>"
  - 该 subagent 修正后重写 JSON，主 agent 再校验，最多重试 2 次
  - 2 次还过不了，停下来告诉用户哪个字段一直错

**注**：模块四（markdown 报告）不走 schema 校验——它的输出是 markdown 不是 JSON。主 agent 只检查 `report.md` 文件存在 + 非空即可。

## 业务规则速查（4 模块共享，subagent prompt 里也会重申）

| 业务规则 | 哪个模块管 |
|---|---|
| 权 1 主题前序（"一种 XX 系统"）作为首条 feature | 模块一 |
| 候选去重 key 用 `(company, product_name)` 二元组 | 模块二 |
| `product_intro` 是自然语言产品介绍（1-2 句关键参数），不参与去重 | 模块二 |
| TOP-N 排序时同公司只保留最高分产品 | 模块二 |
| 数学约束类（D/V、S/E、L/S 等）现场算具体数值 | 模块二/三 |
| `total_score` 只看权 1（非权 1 不进 ranking） | 模块三 |
| 失效只看权 1（仅权 1 任一"明确不满足"或 launch_date 早于专利申请日才 disqualified） | 模块二/三 |
| 权 1 缺口特征必填 `evidence_gap_brief`（两行：还缺 / 下一步建议） | 模块三 |


## 评分规则（模块二/三共享）

| status | ratio | 触发条件 |
|---|---|---|
| 明确满足 | 1.0 | 公开 URL 直接字面/数值证据，≥ 1 独立 host |
| 可能满足 | 0.8 | 公开证据严谨推理（必须给严谨的推理链） |
| 证据不足 | 0.3 | 证据池里找不到相关线索 |
| 明确不满足 | 0.0 | 公开证据直接矛盾 → 整候选 disqualified=true, total_score=0 |

`total_score = mean(各 feature ratio) × 100`。

## 垂类网站推荐（模块二/三 搜索证据时优先用）

[`configs/technology_tags.toml`](configs/technology_tags.toml) 维护两类网站清单（每条带 url + description）：

1. `tags[name == <technology_tag>].recommended_sites`：按技术领域的垂类站点（如"动力电池" → `batteryfinds.com`）
2. 顶层 `[[universal_sites]]`：所有 tag 通用的高信号站点（车型维修手册站、汽修资料站等）

模块二/三 subagent 在 spawn 时主 agent 应把这个 toml 路径告诉它们，让它们**优先**在这些站点检索，而不是从零大海捞针。要新增网站推荐时只动这个 toml 即可。

## 停止条件（subagent 内部判断）

模块二/三 subagent 在搜索阶段：
- **硬规则**：所有权 1 feature 都拿到 ≥1 个独立 host 的明确满足证据 → 停搜
- **软判断**：连续 2-3 轮搜索没找到新有价值证据 → 停搜（subagent 自己评估）
- **不要无限搜，不要陷入死循环**：判断"实在搜不到了"就停，落 `证据不足` 或 `可能满足`

## 触发执行流程

1. **校验用户输入**：只接受完整 `PUBLICATION_NO`；未通过则立即停止并要求用户更正
2. **解析用户输入**：抽出已通过门禁的专利公开号/授权公告号
3. **创建输出目录** + 子目录
4. **顺序 spawn 4 subagent**，传 prompt + 输入 JSON + 输出 JSON 路径
5. **每次跑完读取产物 JSON 做基本验证**
6. **打印 report.md 路径**给用户

完成后告诉用户报告位置。
