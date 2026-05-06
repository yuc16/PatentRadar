# 中国行业站点种子库

每个 JSON 文件代表一个产业领域。`industry_tag` 与文件名一致（不含扩展名）。

阶段 1 拆解时，LLM 会为专利打一个 `industry_tag`。这些站点现在服务两个环节：

- **竞品发现阶段**：DeepSeek Agent 会读取对应领域站点，把候选发现 query 包装成 `site:` 定向检索，用于补充中文行业媒体、协会、厂商官网等来源。
- **证据检索阶段**：三个 Agent 都会读取对应领域站点，但只挑高价值站点类型（厂商官网、规格资料、经销商、供应商、PDF / 产品手册等），派生少量 `site:` query，用于召回规格页、PDF 索引、经销商产品参数和官方资料。

## JSON 字段

```json
{
  "industry_tag": "battery",
  "label": "动力电池 / 储能",
  "sites": [
    {"domain": "d1ev.com", "name": "第一电动网", "type": "行业媒体"}
  ]
}
```

- `industry_tag`：必须等于文件名（不含 `.json`）
- `label`：人类可读名称，仅展示用
- `sites[].domain`：用于 Bocha `site:` 操作符；不带 `https://` 前缀，不带路径
- `sites[].type`：自由文本，用于人工识别和证据阶段筛选。建议使用或包含这些词：`行业媒体`、`研究报告`、`行业协会`、`厂商官网`、`规格资料`、`经销商`、`供应商`、`PDF`、`产品手册`、`论坛 / 规格线索`。

证据阶段会优先使用 `规格资料 / 经销商 / 供应商 / PDF` 这类站点，其次使用 `厂商官网`；论坛类站点默认不作为证据阶段 `site:` 定向入口，只作为人工线索或候选发现补充。

## 调整方法

- 增删条目：直接改 JSON。通用行业媒体放 `general.json`，领域专属规格站或厂商站放对应 `<tag>.json`。
- 新增领域：新建 `<tag>.json`，再在拆解 prompt（[../../src/patentradar/prompts/claim_decompose_system.md](../../src/patentradar/prompts/claim_decompose_system.md)）中把 tag 列入候选枚举，否则 LLM 不会用
- 多语言名：`name` 字段可写中英双语（例如 `比亚迪 BYD`）

## 默认随附领域

| tag | 覆盖 |
|---|---|
| `battery` | 动力 / 储能电池产业链 |
| `semiconductor` | 半导体器件、IC 封装、传感器 |
| `automotive` | 整车 / 汽车电子 / 智能驾驶 |
| `display` | 面板 / 显示模组 |
| `general` | 通用国内行业媒体（任何专利都会附加） |
