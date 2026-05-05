# 中国行业媒体白名单

每个 JSON 文件代表一个产业领域。`industry_tag` 与文件名一致（不含扩展名）。

阶段 1 拆解时，LLM 会为专利打一个 `industry_tag`；阶段 2 DeepSeek Agent 用它选择 query 时拼上的 `site:` 限定。

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
- `sites[].type`：自由文本，用于人工识别（行业媒体 / 企业披露 / 行业协会 / 学术等）

## 调整方法

- 增删条目：直接改 JSON
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
