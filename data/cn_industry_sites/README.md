# 中国行业站点种子库

每个 JSON 文件代表一个产业领域。`industry_tag` 与文件名一致（不含扩展名）。

阶段 1 拆解时，LLM 会为专利打一个 `industry_tag`。这些文件现在服务三个环节：

- **竞品发现阶段**：DeepSeek Agent 会读取对应领域站点，把候选发现 query 包装成 `site:` 定向检索，用于补充中文行业媒体、协会、厂商官网等来源。
- **证据检索阶段**：三个 Agent 都会读取对应领域站点，但只挑高价值站点类型（厂商官网、规格资料、经销商、供应商、PDF / 产品手册等），派生少量 `site:` query，用于召回规格页、PDF 索引、经销商产品参数和官方资料。这里是“额外种子”，不会限制普通中英文 query 的广域搜索。
- **行业证据 profile**：可选的 `evidence_profile` 放行业专属商品名、通用词、英文特征映射、规格页路径提示和补搜 query 模板。通用代码不会内置这些行业词，避免电池词污染半导体、汽车、显示等其他领域。

## JSON 字段

```json
{
  "industry_tag": "battery",
  "label": "动力电池 / 储能",
  "prompt_description": "动力 / 储能电池、电芯、模组、BMS、电池包结构",
  "evidence_profile": {
    "generic_terms": ["电池", "电芯", "battery", "cell"],
    "named_product_hints": ["短刀", "刀片", "short blade"],
    "spec_queries": ["{base} 电芯 规格书 容量 电压 尺寸 datasheet"],
    "product_spec_page_hints": ["battery-cell", "lifepo4-battery"],
    "product_spec_context_terms": ["battery", "cell", "电池", "电芯"],
    "numeric_model_context_terms": ["battery", "cell", "电池", "电芯"],
    "structure_feature_hints": ["极柱", "极耳", "方壳", "刀片"],
    "feature_term_map": [
      {"needles": ["电芯"], "terms": ["battery cell"]}
    ]
  },
  "sites": [
    {"domain": "d1ev.com", "name": "第一电动网", "type": "行业媒体"}
  ]
}
```

- `industry_tag`：必须等于文件名（不含 `.json`）。**该字段同时是 GPT-5.5 拆解器允许输出的 `industry_tag` 真源** —— 拆解 prompt 的取值表和代码里的合法集都从这里自动派生，无需手动改代码。
- `label`：人类可读名称，仅展示用
- `prompt_description`：在拆解 prompt 的"何时选"那栏会展示给 GPT-5.5 看的描述。**此字段决定 GPT-5.5 怎么把专利映射到本领域**，要写得能把判定规则讲清楚（如"动力 / 储能电池、电芯、模组、BMS、电池包结构"）。空字段会回退到 `label`。
- `sites[].domain`：用于 Bocha `site:` 操作符；不带 `https://` 前缀，不带路径
- `sites[].type`：自由文本，用于人工识别和证据阶段筛选。建议使用或包含这些词：`行业媒体`、`研究报告`、`行业协会`、`厂商官网`、`规格资料`、`经销商`、`供应商`、`PDF`、`产品手册`、`论坛 / 规格线索`。
- `evidence_profile.generic_terms`：该行业里过泛、不能单独证明产品明确性的词。
- `evidence_profile.named_product_hints`：该行业常见商品名 / 系列名提示，用于候选准入。
- `evidence_profile.spec_queries`：该行业规格证据补搜模板，支持 `{base}` 占位符（公司 + 产品）。
- `evidence_profile.product_spec_page_hints` / `product_spec_context_terms`：该行业规格页 URL / 标题识别提示。
- `evidence_profile.numeric_model_context_terms`：该行业用于判断纯数字型号是否具体的上下文词。
- `evidence_profile.structure_feature_hints`：该行业用于判断“结构/形态/连接证据目标”的专属结构词。
- `evidence_profile.feature_term_map`：该行业中文特征到英文 query 词的映射，`needles` 命中特征文本后追加 `terms`。

证据阶段会优先使用 `规格资料 / 经销商 / 供应商 / PDF` 这类站点，其次使用 `厂商官网`；论坛类站点默认不作为证据阶段 `site:` 定向入口，只作为人工线索或候选发现补充。为了控制 API 消耗，每个候选只会派生少量行业站点 query，命中后仍要经过公司 / 产品 / 别名相关性过滤。

## 调整方法

- **增删站点条目**：直接改对应 `<tag>.json`。通用行业媒体放 `general.json`，领域专属规格站、厂商站和 `evidence_profile` 放领域文件。
- **新增领域**：**只需新建 `<tag>.json`**，必须包含 `industry_tag` / `label` / `prompt_description` / `sites` 四个字段。`evidence_profile` 可选。系统启动时会自动：
    1. 把新 tag 加入 `cn_industry.valid_tags()`（[../../src/patentradar/search/cn_industry.py](../../src/patentradar/search/cn_industry.py)）
    2. 把 `(industry_tag, prompt_description)` 渲染进拆解 prompt 的取值表
    3. 把 tag 加入 JSON schema 的 `tag1 | tag2 | ...` 提示串
    4. 让 GPT-5.5 输出后通过代码白名单校验
  无需改 [`prompts/claim_decompose_system.md`](../../src/patentradar/prompts/claim_decompose_system.md) 或 [`patent/decomposer.py`](../../src/patentradar/patent/decomposer.py)。
- **删除领域**：直接删 `<tag>.json`。删除前确认没有正在用 `industry_tag=<tag>` 的 `task_package.json`，否则后续阶段会回退到 `general` 白名单。
- **多语言名**：`sites[].name` 字段可写中英双语（例如 `"比亚迪 BYD"`）。

## 默认随附领域

| tag | 覆盖 |
|---|---|
| `battery` | 动力 / 储能电池产业链 |
| `semiconductor` | 半导体器件、IC 封装、传感器 |
| `automotive` | 整车 / 汽车电子 / 智能驾驶 |
| `display` | 面板 / 显示模组 |
| `general` | 通用国内行业媒体（任何专利都会附加） |
