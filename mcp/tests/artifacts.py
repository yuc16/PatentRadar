from __future__ import annotations

from copy import deepcopy


def task_package() -> dict:
    feature = {"feature_id": "C1-F1", "feature_text": "一种测试装置"}
    return {
        "patent": {
            "publication_no": "CN114512759B",
            "country_code": "CN",
            "title": "一种测试装置",
            "applicants": ["申请人公司"],
            "inventors": ["发明人"],
            "application_date": "2022-03-15",
            "google_patents_url": "https://patents.google.com/patent/CN114512759B/zh",
            "pdf_url": "https://patentimages.storage.googleapis.com/test.pdf",
        },
        "claims": [{"claim_no": 1, "claim_text": "一种测试装置", "features": [feature]}],
        "claim_1_text": "一种测试装置",
        "claim_1_features": [feature],
        "technology_tag": "其他",
        "claims_source": "html",
    }


def candidate() -> dict:
    return {
        "candidate_id": "P01",
        "company": "示例公司",
        "company_en": "Example Corp",
        "product_name": "示例产品（SKU-1 / 2024款）",
        "product_name_en": "Example Product (SKU-1 / MY2024)",
        "product_intro": "锁定 SKU-1 的示例产品。",
        "market": "中国市场",
        "reason_for_deep_dive": "与权1保护对象相关",
        "source_result_ids": [],
        "source_urls": ["https://example.com/spec"],
        "initial_evidence_summary": "公开资料未披露完整结构。",
    }


def comparison(*, with_gap: bool) -> dict:
    return {
        "feature_id": "C1-F1",
        "patent_feature": "一种测试装置",
        "competitor_feature": "产品用途接近，但公开结构不足。",
        "status": "证据不足",
        "score": 0.3,
        "evidence": [],
        "reasoning": "现有公开资料没有足以完成逐项判断的技术结构。",
        "suggested_followup_queries": [],
        "evidence_gap_brief": (
            "还缺：SKU-1 的内部结构说明，现有产品介绍不足以证明权1结构。\n"
            "下一步建议：去产品官网或维修资料站下载 SKU-1 技术手册并查看结构章节。"
            if with_gap
            else ""
        ),
    }


def top_competitors() -> dict:
    item = {
        "candidate": candidate(),
        "launch_date": "未明确",
        "launch_date_evidence": [],
        "disqualified": False,
        "disqualification_reason": "",
        "comparisons": [comparison(with_gap=False)],
        "total_score": 30.0,
        "searched_queries": ["示例产品 SKU-1 规格书"],
        "searched_providers": ["codex_builtin"],
    }
    return {"publication_no": "CN114512759B", "top_competitors": [item], "excluded_candidates": []}


def full_claim_chart() -> dict:
    item = {
        "candidate": deepcopy(candidate()),
        "launch_date": "未明确",
        "launch_date_evidence": [],
        "disqualified": False,
        "disqualification_reason": "",
        "claim_charts": [
            {
                "claim_no": 1,
                "claim_text": "一种测试装置",
                "comparisons": [comparison(with_gap=True)],
                "claim_score": 30.0,
            }
        ],
        "claim_1_score": 30.0,
        "total_score": 30.0,
        "searched_queries": ["示例产品 SKU-1 维修手册", "[SKU自检-M3] SKU-1 / 新增 evidence sku 一致性: 全部匹配"],
        "searched_providers": ["codex_builtin"],
    }
    return {"publication_no": "CN114512759B", "top_competitors": [item], "excluded_candidates": []}


def report_artifact() -> dict:
    markdown = """## 1. 专利详细信息

| 字段 | 值 |
|---|---|
| 公开号 | CN114512759B |
| 标题 | 一种测试装置 |
| 申请人 | 申请人公司 |
| 发明人 | 发明人 |
| 申请日 | 2022-03-15 |
| 技术领域 | 其他 |

## 2. 整体侵权风险评估

示例公司示例产品（SKU-1 / 2024款）锁定 SKU-1，权利要求1当前得分为30分。公开材料只能确认产品用途接近，尚不能确认内部技术结构。本结论仅用于公开证据线索筛查，不构成法律意见。

<table><thead><tr><th>排名</th><th>公司 / 产品</th><th>总分</th><th>权 1 明确满足</th><th>缺口 feature</th><th>下一步搜索建议</th></tr></thead><tbody><tr><td>1</td><td>示例公司 / 示例产品（SKU-1 / 2024款）</td><td>30.00</td><td>0/1</td><td>C1-F1</td><td>去产品官网或维修资料站下载 SKU-1 技术手册并查看结构章节</td></tr></tbody></table>

## 3. TOP1 竞品深度对比

#### TOP1: 示例公司 示例产品（SKU-1 / 2024款）

| 字段 | 值 |
|---|---|
| 候选 ID | P01 |
| 公司（中/英） | 示例公司 / Example Corp |
| 产品（中/英） | 示例产品（SKU-1 / 2024款） / Example Product (SKU-1 / MY2024) |
| **SKU 锁定** | SKU-1 / 2024款；本节证据仅指向该 SKU |
| 产品介绍 | 锁定 SKU-1 的示例产品 |
| 市场 | 中国市场 |
| 上市日期 | 未明确 |
| 总分（百分制） | 30.00 |

**逐权利要求对比**：

##### 权利要求 1

> 一种测试装置

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C1-F1 | 一种测试装置 | 产品用途接近但结构未公开 | 证据不足 | — | 现有公开资料没有足以完成逐项判断的技术结构，需人工取得 SKU-1 技术手册复核。 |
"""
    return {"report_markdown": markdown}
