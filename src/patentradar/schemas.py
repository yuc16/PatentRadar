"""产物数据结构（pydantic）。

阶段 1：``TaskPackage`` —— 专利文本 + 权利要求 1 拆解。
阶段 2：``AgentOutput`` —— 单个搜索 Agent 输出 Top5 候选 + 证据 + 特征对比。
阶段 4：``CandidatePool`` —— 三 Agent 输出去重合并后的候选池。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# =============== 阶段 1：专利与权要拆解 ===============


class ClaimFeature(BaseModel):
    feature_id: str = Field(..., description="F1, F2, F3 ...")
    feature_text: str = Field(..., description="原文中对应的技术特征片段（尽量贴原文）")
    engineering_terms: list[str] = Field(default_factory=list, description="工程术语 / 同义表达")
    marketing_terms: list[str] = Field(
        default_factory=list,
        description="中文行业宣传语 / 产品营销话术（用于召回竞品产品页，不是专利术语）",
    )
    is_essential: bool = Field(True, description="是否为必要技术特征")
    notes: Optional[str] = Field(None, description="拆解说明（可选）")


class PatentMeta(BaseModel):
    publication_no: str
    title: Optional[str] = None
    assignees: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    application_date: Optional[str] = Field(None, description="专利申请日，YYYY-MM-DD")
    priority_date: Optional[str] = Field(None, description="优先权日，YYYY-MM-DD")
    source_url: str
    fetched_at: str


class TaskPackage(BaseModel):
    """阶段 1 产物：专利元信息 + 权要 1 原文 + 拆解后的技术特征。"""
    patent: PatentMeta
    claim_1_text: str  # 视觉重建后的最终版，公式以 LaTeX 表达
    claim_1_text_html: Optional[str] = None
    claim_1_source: str = "vision_pdf"  # vision_pdf | html
    claim_features: list[ClaimFeature]
    industry_tag: Optional[str] = Field(
        None,
        description="产业领域标签，用于路由中文行业媒体白名单 (battery / semiconductor / automotive / display / general / null)",
    )
    decomposer_model: str
    pdf_url: Optional[str] = None


# =============== 阶段 2：Agent 检索输出 ===============


SourceType = Literal[
    "官网",
    "官方PDF",
    "产品手册",
    "白皮书",
    "新闻稿",
    "专利文献",
    "标准",
    "认证资料",
    "年报",
    "招股书",
    "权威媒体",
    "行业报告",
    "研究报告",
    "普通新闻",
    "展会报道",
    "自媒体",
    "论坛",
    "二手转载",
    "其他",
]
SourceReliability = Literal["high", "medium", "low"]


class Evidence(BaseModel):
    """单条公开证据。"""
    url: str
    title: str = ""
    source_type: SourceType = "其他"
    source_reliability: SourceReliability = "medium"
    summary: str = Field("", description="证据摘要 / 关键信息片段")
    supported_features: list[str] = Field(
        default_factory=list, description="该证据支撑的特征 ID 列表，例如 ['F1','F3']"
    )


Judgement = Literal["明确满足", "可能满足", "证据不足", "明确不满足"]


class FeatureMatch(BaseModel):
    """单个候选竞品的单条特征判断（PRD §10）。"""
    feature_id: str
    claim_feature: str = Field("", description="该特征在权利要求 1 中的原文（便于人工核查）")
    judgement: Judgement
    score: float = Field(..., description="1.0 / 0.8 / 0.3，明确不满足时为 0 但候选会被排除")
    reasoning: str = Field("", description="判断理由（可能满足时必须给推理链）")
    evidence: list[Evidence] = Field(default_factory=list)


class HardRuleCheck(BaseModel):
    """PRD §9 硬性规则的可机读结果。"""
    is_patent_owner_product: bool = Field(False, description="是否专利权人/申请人/关联主体产品")
    has_clear_company: bool = True
    has_clear_product: bool = True
    has_public_evidence: bool = True
    has_any_clearly_unmatched_feature: bool = False
    patent_application_date: Optional[str] = None
    product_launch_date: Optional[str] = None
    product_launch_after_application: Optional[bool] = Field(
        None,
        description="True=上市/发布/量产日期明确晚于申请日；False=明确不晚于申请日；None=无法确定",
    )
    notes: Optional[str] = None


class Candidate(BaseModel):
    """单个 Agent 输出中的候选竞品。"""
    rank: int
    company: str
    product: str
    aliases: list[str] = Field(default_factory=list)
    product_launch_date: Optional[str] = Field(
        None,
        description="公开证据中可识别的产品上市/发布/量产日期；无法确定时为空",
    )
    product_launch_date_evidence_url: Optional[str] = None
    score: float = Field(..., description="0~100 范围，按 PRD §10.3 计算")
    hard_rule_check: HardRuleCheck
    feature_match_table: list[FeatureMatch]
    main_evidence_urls: list[str] = Field(default_factory=list)
    remaining_gaps: list[dict] = Field(
        default_factory=list,
        description="尚未补齐的证据缺口，元素形如 {feature_id, gap}",
    )
    reason_for_top5: str = ""


class DiscardedCandidate(BaseModel):
    company: str = ""
    product: str = ""
    discard_reason: str
    evidence_urls: list[str] = Field(default_factory=list)


class QueryRecord(BaseModel):
    query: str
    search_engine: str  # bocha / exa / brave / tavily / jina
    purpose: Literal["候选竞品发现", "证据检索"] = "候选竞品发现"
    n_results: int = 0


class AgentOutput(BaseModel):
    """单个搜索 Agent 输出（PRD §13）。"""
    agent_name: str
    search_perspective: str  # PRD §6.3
    patent_publication_no: str
    queries_used: list[QueryRecord] = Field(default_factory=list)
    top5_candidates: list[Candidate] = Field(default_factory=list)
    discarded_candidates: list[DiscardedCandidate] = Field(default_factory=list)
    notes: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    llm_model: Optional[str] = None


# =============== 阶段 4：合并候选池 ===============


class CandidateEvidenceMerged(Evidence):
    evidence_id: str = ""
    found_by_agents: list[str] = Field(default_factory=list)


class AgentJudgement(BaseModel):
    """同一个候选 × 同一个特征 × 各 agent 的判断快照。"""
    agent_name: str
    judgement: Judgement
    score: float
    reasoning: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class FeatureJudgementMerged(BaseModel):
    feature_id: str
    agent_judgements: list[AgentJudgement] = Field(default_factory=list)


class CandidateInPool(BaseModel):
    """合并后的候选竞品（PRD §12.2）。"""
    candidate_id: str
    company: str
    product: str
    aliases: list[str] = Field(default_factory=list)
    found_by_agents: list[str] = Field(default_factory=list)
    all_evidence: list[CandidateEvidenceMerged] = Field(default_factory=list)
    preliminary_feature_table: list[FeatureJudgementMerged] = Field(default_factory=list)
    known_gaps: list[dict] = Field(default_factory=list)


class CandidatePool(BaseModel):
    """阶段 4 产物。"""
    patent_publication_no: str
    claim_1_text: str
    claim_features: list[ClaimFeature]
    candidate_pool: list[CandidateInPool] = Field(default_factory=list)


# =============== 阶段 4 末：GPT-5.5 最终复核输出 ===============


RiskLevel = Literal["高度疑似落入", "中度疑似", "局部相似", "弱相关"]


class FinalCandidate(BaseModel):
    """复核后的最终候选（PRD §11 + §15）。"""
    rank: int
    candidate_id: str
    company: str
    product: str
    aliases: list[str] = Field(default_factory=list)
    product_launch_date: Optional[str] = None
    product_launch_date_evidence_url: Optional[str] = None
    score: float
    risk_level: RiskLevel
    final_feature_table: list[FeatureMatch]
    main_evidence_urls: list[str] = Field(default_factory=list)
    reason_for_top5: str = ""
    remaining_gaps: list[dict] = Field(default_factory=list)


class ReviewExcluded(BaseModel):
    candidate_id: str = ""
    company: str = ""
    product: str = ""
    discard_reason: str
    evidence_urls: list[str] = Field(default_factory=list)


class NeedsManualReview(BaseModel):
    candidate_id: str = ""
    company: str = ""
    product: str = ""
    gap: str
    suggested_search_direction: str = ""


class FinalReport(BaseModel):
    """阶段 4 末产物，喂给阶段 5 报告生成。"""
    patent_publication_no: str
    claim_1_text: str
    claim_features: list[ClaimFeature]
    top5: list[FinalCandidate] = Field(default_factory=list)
    excluded: list[ReviewExcluded] = Field(default_factory=list)
    needs_manual_review: list[NeedsManualReview] = Field(default_factory=list)
    reviewer_model: str = ""
    elapsed_seconds: float = 0.0
    notes: str = ""
