# task_package.json schema

模块一输出的 JSON 结构。所有 subagent 共享读取。

## 字段定义

| 字段路径 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `patent.publication_no` | string | ✅ | 专利公开号（保留原大小写，如 `CN114512759B`） |
| `patent.country_code` | string | ✅ | 国家代码（CN/US/EP/JP/KR/...）|
| `patent.title` | string | ✅ | 专利标题（保留原语言） |
| `patent.applicants` | string[] | ✅ | 申请人列表 |
| `patent.inventors` | string[] | ✅ | 发明人列表 |
| `patent.application_date` | string | ✅ | 申请日，`YYYY-MM-DD` |
| `patent.google_patents_url` | string | ✅ | Google Patents URL |
| `patent.pdf_url` | string | 可选 | 官方 PDF URL（仅当抓到时填）|
| `claims` | object[] | ✅ | 全部权利要求 |
| `claims[].claim_no` | int | ✅ | 权利要求编号（1, 2, 3, ...）|
| `claims[].claim_text` | string | ✅ | 完整原文（含前序）|
| `claims[].features` | object[] | ✅ | 拆解后的 feature 列表 |
| `claims[].features[].feature_id` | string | ✅ | 格式 `C{claim_no}-F{idx}`，idx 从 1 起 |
| `claims[].features[].feature_text` | string | ✅ | feature 文本（必须是 claim_text 的连续片段，或对实质型权利要求的主题前序） |
| `claim_1_text` | string | ✅ | 权 1 完整原文（== `claims[0].claim_text`） |
| `claim_1_features` | object[] | ✅ | 权 1 features（== `claims[0].features`） |
| `technology_tag` | string | ✅ | 技术领域标签 |
| `claims_source` | string | ✅ | `"html"` / `"pdf_vision"` / `"mixed"` |

## 示例

```json
{
  "patent": {
    "publication_no": "CN114512759B",
    "country_code": "CN",
    "title": "一种锂离子电池及电芯",
    "applicants": ["蜂巢能源科技股份有限公司"],
    "inventors": ["..."],
    "application_date": "2022-03-15",
    "google_patents_url": "https://patents.google.com/patent/CN114512759B/zh",
    "pdf_url": "https://patentimages.storage.googleapis.com/.../CN114512759B.pdf"
  },
  "claims": [
    {
      "claim_no": 1,
      "claim_text": "1.一种锂离子电池电芯，其特征在于，包括：长方体电池本体；所述电池本体满足：D/V= 0.0000065 mm⁻² ~ 0.00002 mm⁻²；...",
      "features": [
        {"feature_id": "C1-F1", "feature_text": "一种锂离子电池电芯"},
        {"feature_id": "C1-F2", "feature_text": "包括：长方体电池本体"},
        {"feature_id": "C1-F3", "feature_text": "所述电池本体满足：D/V= 0.0000065 mm⁻² ~ 0.00002 mm⁻²"}
      ]
    },
    {
      "claim_no": 2,
      "claim_text": "...",
      "features": [
        {"feature_id": "C2-F1", "feature_text": "..."}
      ]
    }
  ],
  "claim_1_text": "1.一种锂离子电池电芯...",
  "claim_1_features": [
    {"feature_id": "C1-F1", "feature_text": "一种锂离子电池电芯"}
  ],
  "technology_tag": "动力电池",
  "claims_source": "html"
}
```

## 关键约束
- `claim_no` 严格递增（1, 2, 3, ...）
- `feature_id` 严格按 `C{claim_no}-F{idx}` 格式
- `feature_text` 是 `claim_text` 的连续片段（**主题前序例外**：实质型权利要求的"一种 XX"作为首条 feature 时，可以是抽取出的主题部分）
- 引用条款（"应用于权利要求 X-Y..."）**不作为 feature**
- 公式 + 变量定义合并为同一条 feature
