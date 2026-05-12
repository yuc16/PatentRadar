# 模块四：report

> 把模块一拆解结果 + 模块三完整对比 JSON 渲染成一份**结构清晰、可人工复核**的专利竞品分析 markdown 报告。
>
> 当 TOP5 中存在 ≥ 80 分的竞品时，**额外**生成一个 Google Patents 高级检索深链接（同国家 + 同申请人 + 同标题预过滤），让人工点开浏览器核查本专利的同族延续案/分案——这些大概率面临同样的侵权风险。

输入：
- 模块一 [`task_package.json`](../../../../tests/decompose/outputs/CN114512759B/task_package.json)
- 模块三 [`top5_full_claim_chart.json`](../../../../tests/full_claim_chart/outputs/CN114512759B/top5_full_claim_chart.json)

输出：
- `report.md`：完整 markdown 报告
- `report.pdf`：基于 markdown 渲染的 PDF（WeasyPrint，A4 + PingFang SC）
- `similar_patents.json`：相似专利深链接（仅 max_total_score ≥ 80 时生成）

---

> **LLM backend 全局可切换**：报告渲染走 `get_llm_provider().chat_text()`。默认 ChatGPT OAuth (Codex)，设置 `PATENTRADAR_LLM_BACKEND=openai` + `PATENTRADAR_OPENAI_BASE_URL` + `PATENTRADAR_OPENAI_API_KEY` 即可切到 OpenAI 兼容服务。报告生成不需要 vision，无需关心 `PATENTRADAR_OPENAI_VISION`。

## 流程

```
1. 加载 task_package + full_claim_chart
2. 计算 max_total_score = max(top_competitors[].total_score)
3. 若 max_total_score ≥ 80（INFRINGEMENT_RISK_THRESHOLD），构造 Google Patents 高级检索 URL：
   - 国家：源专利公开号前缀（CN/US/EP/JP/…）
   - 申请人：task_package.patent.applicants[0]（原文照搬）
   - 标题：task_package.patent.title（用双引号）
   - 写入 similar_patents.json
4. 单次 LLM 调用生成 markdown report:
   - 输入: task_package + top5 + excluded + similar_patents_hint
   - prompt: 6 章节固定结构 + 强制每条 feature 都写进表格
5. 落盘 report.md
6. WeasyPrint 渲染 report.md → report.pdf（A4，PingFang SC，clickable links；
   PDF 渲染失败不阻断主流程，md 仍会保存）
```

为什么不爬：Google Patents 的 xhr/query 端点对自动化访问反应剧烈（连续几次就 HTTP 503 锁定），且默认按 INPADOC 同族去重——「找同族延续案/分案」恰恰是我们最想要的，而这又恰恰是它最不愿意返回的。直接交给人工浏览器最快最稳。

---

## 报告章节固定结构

| # | 章节 | 内容 |
|---|---|---|
| 1 | 专利详细信息 | 字段表 + 权 1 完整原文引用 |
| 2 | 整体侵权风险评估 | LLM 自然语言双视角（业务 + 律师） |
| 3 | TOP5 竞品对比 | 每候选一节，含每条权利要求逐特征表（feature_id / 权利要求技术特征 / 竞品对应特征 / 状态 / 证据 URL / 说明）。证据 URL 列**多链接时按 `1. <link>` `2. <link>` 有序编号**（编号是裸字符，不是 markdown 列表语法——表格单元格内列表不渲染）|
| 4 | 下一步建议 | LLM 3-5 条 bullet |
| 5 | 失格候选附录 | 简表，含失格原因 |
| 6 | 相似专利人工核查 | 仅 max_score ≥ 80 时出现，包含国家/申请人/标题字段表 + 一条预过滤好的 Google Patents 高级检索深链接 |

---

## 运行方式

### 测试脚本

```bash
python tests/report/run_report.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --full-claim-chart tests/full_claim_chart/outputs/CN114512759B/top5_full_claim_chart.json \
  --output-dir tests/report/outputs/CN114512759B
```

### CLI

```bash
patentradar report \
  tests/decompose/outputs/CN114512759B/task_package.json \
  tests/full_claim_chart/outputs/CN114512759B/top5_full_claim_chart.json \
  --output-dir data/output/CN114512759B
```

---

## 性能预估

| 阶段 | 耗时 |
|---|---|
| 相似专利深链接 | < 1ms（纯字符串拼接，无网络调用） |
| 单次 LLM 调用生成报告 | 1-5 分钟（context ~200KB，reasoning=high） |
| WeasyPrint 渲染 PDF | ~1-2 秒 |
| **单专利总耗时** | **~1-5 分钟** |

---

## PDF 渲染依赖

PDF 输出走 [WeasyPrint](https://weasyprint.org/)，需要系统层 Cairo / Pango：

```bash
brew install pango                  # macOS
uv add weasyprint markdown          # Python 侧依赖（已纳入 pyproject.toml）
```

CSS 在 [`pipeline.py:render_pdf`](pipeline.py) 函数内联：A4 + 18mm/14mm 边距、PingFang SC 主字体、表格 `table-layout: fixed` 等宽列（防止「状态」短列把 `明确不满足` 挤成竖排）、`tr { break-inside: avoid }` 防止行被切到两页之间。

要换字体/边距/颜色：直接改 `render_pdf` 里那段 CSS 字符串，无外部样式文件。
