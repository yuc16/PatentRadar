---
name: patentradar
description: 专利侵权竞品分析 skill。输入专利公开号（CN/US/EP/JP 等），输出可人工复核的 markdown 竞品分析报告。工作流：拆解权利要求 → 搜索市场竞品 → 抓证据（含图像）→ 全部权利要求逐特征对比 → 生成报告。触发词：专利侵权分析、专利竞品、claim chart、专利公开号、CN/US/EP/JP 专利号、专利对比、技术特征对比、专利保护范围、侵权风险评估。不适用：专利申请文书撰写、专利无效宣告、知识产权法律咨询、专利诉讼策略。
---

# PatentRadar 专利侵权竞品分析

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

确认用户给出的专利公开号（如 `CN114512759B`）。如果不清楚，问用户。

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
- 权 1 至少 4 条 features
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

### 步骤 4：spawn subagent — 生成报告

用 Task tool spawn subagent，prompt 加载 `agents/report.md` + module_1 + module_3 输出文件路径。

**期望输出**：`<output_dir>/module_4/report.md`。

### 步骤 5：交付

打印报告路径给用户。如果用户需要 PDF，提示可以用 WeasyPrint 渲染（项目内已有渲染逻辑可参考 `src/patentradar/modules/report/pipeline.py` 的 `render_pdf` 函数）。

## 主 agent 的职责（要做什么 / 不要做什么）

**要做**：
- 按顺序 spawn 4 个 subagent，每次传清楚 prompt 文件路径 + 输入 JSON 路径 + 输出 JSON 路径
- 每个 subagent 跑完读其输出 JSON，**做最小合理性检查**（schema 字段齐全、数量合理），不做语义判断
- 出错时把错误信息透传给用户，问要不要重试该模块

**不要做**：
- 主 agent 不要自己抓页面、不要自己看图、不要自己写报告内容 —— 全部由 subagent 干
- 不要把 4 个模块合并到一次调用（每个模块用独立 subagent 隔离上下文）
- 不要给 subagent 加额外的硬性约束（如 query 上限、看图上限等）—— subagent 自己决定何时够了

## 业务规则速查（4 模块共享，subagent prompt 里也会重申）

| 业务规则 | 哪个模块管 |
|---|---|
| 权 1 主题前序（"一种 XX 系统"）作为首条 feature | 模块一 |
| 候选去重 key 用 `(company, product_name)` 二元组 | 模块二 |
| `product_version` 是自然语言产品介绍（1-2 句关键参数），不参与去重 | 模块二 |
| TOP-N 排序时同公司只保留最高分产品 | 模块二 |
| 数学约束类（D/V、S/E、L/S 等）现场算具体数值 | 模块二/三 |
| `total_score` 只看权 1（非权 1 不进 ranking） | 模块三 |
| 失格只看权 1（仅权 1 任一"明确不满足"或 launch_date 早于专利申请日才 disqualified） | 模块二/三 |
| 权 1 缺口特征必填 `evidence_gap_brief`（两行：还缺 / 下一步建议） | 模块三 |
| 报告第 1 章节不展示权 1 原文 | 模块四 |
| 报告 TOP-N 表格无权 1 分数列 / 无深挖理由 / 无 claim_score | 模块四 |
| 报告下一步建议直接复用 `evidence_gap_brief`，不要造 query | 模块四 |

## 评分规则（模块二/三共享）

| status | ratio | 触发条件 |
|---|---|---|
| 明确满足 | 1.0 | 公开 URL 直接字面/数值证据，≥ 1 独立 host |
| 可能满足 | 0.8 | 公开证据严谨推理（必须给推理链） |
| 证据不足 | 0.3 | 证据池里找不到相关线索 |
| 明确不满足 | 0.0 | 公开证据直接矛盾 → 整候选 disqualified=true, total_score=0 |

`total_score = mean(各 feature ratio) × 100`。

## 停止条件（subagent 内部判断）

模块二/三 subagent 在搜索阶段：
- **硬规则**：所有权 1 feature 都拿到 ≥1 个独立 host 的明确满足证据 → 停搜
- **软判断**：连续 2-3 轮搜索没找到新有价值证据 → 停搜（subagent 自己评估）
- **不要无限搜**：判断"实在搜不到了"就停，落 `证据不足` 或 `可能满足`

## 触发执行流程

1. **解析用户输入**：抽出专利公开号
2. **创建输出目录** + 子目录
3. **顺序 spawn 4 subagent**，传 prompt + 输入 JSON + 输出 JSON 路径
4. **每次跑完读取产物 JSON 做基本验证**
5. **打印 report.md 路径**给用户

完成后告诉用户报告位置 + 关键发现摘要（如最高分竞品 / 是否触发 ≥80 风险 / 失格候选数）。
