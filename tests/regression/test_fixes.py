"""Regression tests for code-review fixes (no network / no LLM).

Each test pins one previously-shipped bug so the same regression can't sneak
back in. Keep these focused and fast.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException


class FullClaimChartScrubFieldNameTest(unittest.TestCase):
    """Bug X1: full_claim_chart_worker._drop_empty_url_evidence 旧版用了
    单数字段名 `claim_chart`，与 schema 的 `claim_charts` 不一致，scrub 永远
    空跑，空 URL evidence 透传到 Pydantic 让整个 round 崩。

    顺便覆盖 X3：scrub 完发现 evidence 列表空了 → status 同步降级到「证据不足」。
    """

    def test_scrub_walks_claim_charts_not_claim_chart(self) -> None:
        from patentradar.llm.workers.full_claim_chart_worker import (
            _drop_empty_url_evidence,
        )

        payload = {
            "claim_charts": [
                {
                    "comparisons": [
                        {
                            "feature_id": "C1-F1",
                            "status": "明确满足",
                            "score": 1.0,
                            "evidence": [
                                {"url": "", "title": "", "source_name": "", "snippet": ""}
                            ],
                            "reasoning": "原推理",
                        }
                    ]
                }
            ],
            "launch_date_evidence": [
                {"url": "", "title": "", "source_name": "", "snippet": ""},
                {"url": "https://e.com/a", "title": "t", "source_name": "s", "snippet": "x"},
            ],
        }

        _drop_empty_url_evidence(payload)

        cmp = payload["claim_charts"][0]["comparisons"][0]
        self.assertEqual(cmp["evidence"], [], "空 URL evidence 未被剔除")
        self.assertEqual(cmp["status"], "证据不足", "X3: status 未同步降级")
        # 注：score 不由 scrub 设置，由 FeatureComparison.validate_score
        # 按 status 强制重写（"证据不足" → 0.3），见 schemas/evidence.py。
        self.assertIn("URL 为空", cmp["reasoning"])
        # launch_date_evidence 同样应该只保留合法 URL
        self.assertEqual(len(payload["launch_date_evidence"]), 1)
        self.assertEqual(payload["launch_date_evidence"][0]["url"], "https://e.com/a")

    def test_typo_field_name_not_referenced(self) -> None:
        """硬卡住源码不再出现 payload.get(\"claim_chart\")（单数）"""
        import inspect

        from patentradar.llm.workers.full_claim_chart_worker import (
            _drop_empty_url_evidence,
        )

        src = inspect.getsource(_drop_empty_url_evidence)
        # 注释行允许出现单数；只检查代码行
        code_only = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        self.assertNotIn('payload.get("claim_chart")', code_only)
        self.assertIn('payload.get("claim_charts")', code_only)


class SafeResolvePrefixTraversalTest(unittest.TestCase):
    """Bug 4 (path traversal): _safe_resolve 必须用 Path.relative_to 拦截前缀
    匹配越权（root=/x/AB，filename=../ABC/foo 资源解析后路径仍以 /x/AB 前缀
    开头，但实际指向兄弟目录）。"""

    def test_rejects_sibling_prefix_traversal(self) -> None:
        from patentradar.server.app import _safe_resolve

        with tempfile.TemporaryDirectory() as tmp:
            root_ab = Path(tmp) / "AB"
            root_abc = Path(tmp) / "ABC"
            root_ab.mkdir()
            root_abc.mkdir()
            (root_abc / "secret.json").write_text("sensitive", encoding="utf-8")

            with self.assertRaises(HTTPException) as ctx:
                _safe_resolve(root_ab, "../ABC/secret.json")
            self.assertEqual(ctx.exception.status_code, 400)

    def test_legitimate_subpath_passes(self) -> None:
        from patentradar.server.app import _safe_resolve

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "AB"
            root.mkdir()
            (root / "ok.json").write_text("y", encoding="utf-8")
            target = _safe_resolve(root, "ok.json")
            self.assertEqual(target, (root / "ok.json").resolve())


class RankPagesDensityUsesHaystackLengthTest(unittest.TestCase):
    """Bug F: rank_pages_by_relevance 旧版用 len(text) 作密度分母，短 title
    高命中会让分子膨胀（hits 包含 title 命中）但分母只算 text，相对密度虚高
    把短噪声页推到前面。修复后分母改为 len(haystack)=len(title+text)。"""

    def test_density_normalized_by_haystack_not_text(self) -> None:
        from patentradar.search.relevance import _keyword_hits

        # 直接验下游公式：构造一个 page 让两种分母拉开差距
        title = "Tesla " * 100  # 600 chars，全是命中（但单 keyword cap=3）
        text = "x" * 1000  # 0 命中
        keywords = ["Tesla"]

        haystack = f"{title} {text}"
        hits = _keyword_hits(haystack, keywords)  # cap 到 3
        old_density = (hits / max(1, len(text))) * 1000  # 3/1000*1000 = 3.0
        new_density = (hits / max(1, len(haystack))) * 1000  # 3/1601*1000 ≈ 1.87

        self.assertGreater(
            old_density, new_density,
            "测试预设无效：旧公式应给出更高 density 才能体现 bug",
        )

        # 真实排序函数行为：验证修复后用的是 haystack 长度
        import inspect

        from patentradar.search import relevance

        src = inspect.getsource(relevance.rank_pages_by_relevance)
        self.assertIn("len(haystack)", src)
        self.assertNotIn("hits / max(1, len(text))", src)


class Module2FailedCandidateIsNotCachedTest(unittest.TestCase):
    """Bug B: 模块 2 单候选 LLM/网络异常时旧版会把 fallback `disqualified=True`
    写到 step4_candidates/<cid>.json，下次重跑直接 load cache → 候选被永久排除。
    修复后 fallback 只在本次 run 内存里返回，不写盘。"""

    def _make_minimal_inputs(self):
        from patentradar.schemas import (
            ApplicantSelfSignals,
            Candidate,
            CandidateShortlist,
            ClaimFeature,
            PatentInfo,
            QueryPlan,
            SearchQuery,
            TaskPackage,
        )

        patent = PatentInfo(
            publication_no="CN999999A",
            title="t",
            applicants=["A"],
            google_patents_url="https://patents.google.com/patent/CN999999A",
            fetched_at="2026-01-01T00:00:00+08:00",
        )
        from patentradar.schemas import Claim

        claim_1 = Claim(
            claim_no=1,
            claim_text="一种方法",
            features=[ClaimFeature(feature_id="C1-F1", feature_text="步骤A")],
        )
        task_package = TaskPackage(
            patent=patent,
            technology_tag="其他",
            claims=[claim_1],
            claim_1_text=claim_1.claim_text,
            claim_1_features=claim_1.features,
            claims_source="html",
            model="test",
            reasoning_effort="medium",
        )
        cand = Candidate(
            candidate_id="P01",
            company="测试公司",
            product_name="测试产品",
            market="zh",
            reason_for_deep_dive="t",
            initial_evidence_summary="t",
        )
        shortlist = CandidateShortlist(
            publication_no=patent.publication_no, candidates=[cand]
        )
        # query_plan 仅作占位（disabled-via-cache 路径下 self_signals 用得到）
        query_plan = QueryPlan(
            publication_no=patent.publication_no,
            claim_1_summary="t",
            applicant_self_signals=ApplicantSelfSignals(),
            queries=[
                SearchQuery(
                    query_id=f"Q{i:02d}", query=f"q{i}", intent="evidence",
                    language="zh", target_feature_ids=[], preferred_providers=[],
                )
                for i in range(1, 31)
            ],
        )
        return task_package, shortlist, query_plan

    def test_transient_failure_does_not_write_cache_file(self) -> None:
        from patentradar.modules.competitor_search import pipeline as m2_pipeline

        task_package, shortlist, query_plan = self._make_minimal_inputs()

        # 让底层 map_evidence_for_batch 永远抛网络错。 _process 内部调它，
        # _load_or_run 应该 catch 后返回 in-memory fallback 而非写盘。
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch.object(
                m2_pipeline,
                "map_evidence_for_batch",
                side_effect=RuntimeError("transient network blip"),
            ):
                result = m2_pipeline.run_step4_map_evidence(
                    task_package=task_package,
                    shortlist=shortlist,
                    output_dir=output_dir,
                    query_plan=query_plan,
                    max_workers=1,
                )

            cache_file = output_dir / "step4_candidates" / "P01.json"
            self.assertFalse(
                cache_file.exists(),
                "Bug B 回归：失败 fallback 不应被 cache 到磁盘",
            )
            # 但本次 run 内存里应当有 disqualified 占位，让 step5 排序还能跑
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0].disqualified)
            self.assertIn("LLM/网络异常", result[0].disqualification_reason)


class Module3FailedCandidateIsolationTest(unittest.TestCase):
    """Bug 1 (module-3 error isolation): 旧版任何一个候选 future.result() 抛错
    会冒泡 → 已完成候选的 round2 结果一同丢失。修复后用 `_failed_candidate_placeholder`
    占位让其他候选继续可见。

    本测试 mock `_process_one_candidate`：让 P01 正常返回、P02 抛 RuntimeError。
    断言 run_full_claim_chart 返回的报告：
      - P01 在 top_competitors（其结果未被 P02 异常拖累）
      - P02 走 excluded_candidates（disqualified=True 占位）
    """

    def _make_top_report(self, candidate_ids):
        from patentradar.schemas import (
            Candidate,
            CandidateEvidence,
            FeatureComparison,
            TopCompetitorReport,
        )

        evidences = []
        for cid in candidate_ids:
            cand = Candidate(
                candidate_id=cid,
                company=f"公司{cid}",
                product_name=f"产品{cid}",
                market="zh",
                reason_for_deep_dive="t",
                initial_evidence_summary="t",
            )
            evidences.append(
                CandidateEvidence(
                    candidate=cand,
                    launch_date="2024-01-01",
                    launch_date_evidence=[],
                    comparisons=[
                        FeatureComparison(
                            feature_id="C1-F1", patent_feature="x",
                            competitor_feature="y", status="明确满足",
                            score=1.0, evidence=[], reasoning="r",
                        )
                    ],
                    total_score=100.0,
                )
            )
        return TopCompetitorReport(publication_no="CN999999A", top_competitors=evidences)

    def _make_task_package(self):
        from patentradar.schemas import (
            Claim,
            ClaimFeature,
            PatentInfo,
            TaskPackage,
        )

        patent = PatentInfo(
            publication_no="CN999999A",
            title="t",
            applicants=["A"],
            google_patents_url="https://patents.google.com/patent/CN999999A",
            fetched_at="2026-01-01T00:00:00+08:00",
        )
        claim_1 = Claim(
            claim_no=1,
            claim_text="一种方法",
            features=[ClaimFeature(feature_id="C1-F1", feature_text="步骤A")],
        )
        return TaskPackage(
            patent=patent,
            technology_tag="其他",
            claims=[claim_1],
            claim_1_text=claim_1.claim_text,
            claim_1_features=claim_1.features,
            claims_source="html",
            model="test",
            reasoning_effort="medium",
        )

    def test_one_candidate_failure_does_not_drop_others(self) -> None:
        from patentradar.modules.full_claim_chart import pipeline as m3_pipeline
        from patentradar.schemas import (
            ClaimChartEntry,
            FeatureComparison,
            FullClaimChartCandidate,
        )

        tp = self._make_task_package()
        top_report = self._make_top_report(["P01", "P02"])

        def fake_process(*, module_two_evidence, **_kwargs):
            cid = module_two_evidence.candidate.candidate_id
            if cid == "P02":
                raise RuntimeError("simulated LLM crash")
            # P01 正常返回完整 chart
            return FullClaimChartCandidate(
                candidate=module_two_evidence.candidate,
                launch_date=module_two_evidence.launch_date,
                launch_date_evidence=[],
                claim_charts=[
                    ClaimChartEntry(
                        claim_no=1,
                        claim_text="一种方法",
                        comparisons=[
                            FeatureComparison(
                                feature_id="C1-F1", patent_feature="步骤A",
                                competitor_feature="完全相同", status="明确满足",
                                score=1.0, evidence=[], reasoning="r",
                            )
                        ],
                        claim_score=100.0,
                    )
                ],
                claim_1_score=100.0,
                total_score=100.0,
            )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                m3_pipeline, "_process_one_candidate", side_effect=fake_process
            ):
                report = m3_pipeline.run_full_claim_chart(
                    task_package=tp,
                    top_report=top_report,
                    output_dir=Path(tmp),
                    max_workers=2,
                )

        top_ids = [c.candidate.candidate_id for c in report.top_competitors]
        excluded_ids = [c.candidate.candidate_id for c in report.excluded_candidates]

        self.assertIn("P01", top_ids, "P01 的成功结果被 P02 异常吞掉了")
        self.assertIn("P02", excluded_ids, "P02 应当走 excluded 占位")
        self.assertNotIn("P02", top_ids)
        # P02 的占位应当被标记 disqualified 并带错误原因
        p02 = next(c for c in report.excluded_candidates if c.candidate.candidate_id == "P02")
        self.assertTrue(p02.disqualified)
        self.assertIn("模块3异常", p02.disqualification_reason)


class FailedCandidatePlaceholderSchemaTest(unittest.TestCase):
    """验证 _failed_candidate_placeholder 返回的对象通过 Pydantic 验证、
    被正确路由到 excluded_candidates（不会污染 top_competitors），且模块 4
    overview 用的 `next(...)` 访问模式不会因 claim_charts 异形而崩。"""

    def _dummy_evidence(self, cid="P01"):
        from patentradar.schemas import Candidate, CandidateEvidence

        cand = Candidate(
            candidate_id=cid, company="X", company_en="", product_name="Y",
            product_name_en="", product_version="v1", market="zh",
            reason_for_deep_dive="t", source_result_ids=[], source_urls=[],
            initial_evidence_summary="t",
        )
        return CandidateEvidence(
            candidate=cand, launch_date="", launch_date_evidence=[],
            comparisons=[], total_score=0.0,
        )

    def test_placeholder_passes_pydantic_validation(self) -> None:
        from patentradar.modules.full_claim_chart.pipeline import (
            _failed_candidate_placeholder,
        )

        placeholder = _failed_candidate_placeholder(
            self._dummy_evidence(), reason="simulated crash"
        )
        self.assertTrue(placeholder.disqualified)
        self.assertEqual(placeholder.total_score, 0.0)
        # claim_charts 必须非空（schema 强制），且首条是 claim 1
        self.assertGreaterEqual(len(placeholder.claim_charts), 1)
        self.assertEqual(placeholder.claim_charts[0].claim_no, 1)

    def test_report_worker_overview_handles_empty_comparisons(self) -> None:
        """模块 4 overview summary 用 `next((e for e in claim_charts if e.claim_no==1), None)`
        + `for cmp in claim_1.comparisons`，应当能容忍空 comparisons 列表。
        """
        from patentradar.llm.workers.report_worker import (
            _summarize_candidate_for_overview,
        )
        from patentradar.modules.full_claim_chart.pipeline import (
            _failed_candidate_placeholder,
        )

        placeholder = _failed_candidate_placeholder(
            self._dummy_evidence(), reason="x"
        )
        summary = _summarize_candidate_for_overview(placeholder)
        self.assertEqual(summary["candidate_id"], "P01")
        # comparisons 空 → 摘要里 claim_1_features 也是空 list（而不是 KeyError）
        self.assertEqual(summary["claim_1_features"], [])


class StartRunRejectsInvalidPubTest(unittest.TestCase):
    """新 bug：POST /api/run/{pub} 旧版只做宽松 alnum 校验（"xyz123" 也过），
    错号会被 BackgroundTask 启动 → 前端误以为 {"started": true}，且会留下
    data/output/<pub>/ + logs/<pub>/ 孤儿目录。
    修复：入口同步调 normalize_publication_no，失败 400。"""

    def test_invalid_pub_returns_400_synchronously(self) -> None:
        from fastapi.testclient import TestClient

        from patentradar.server import app as app_module

        # mock 掉 run_pipeline 防止真启动 BackgroundTask；通过断言它未被调用
        # 间接验证入口同步 reject。
        with mock.patch.object(app_module, "run_pipeline") as mocked_run:
            client = TestClient(app_module.app)
            r = client.post("/api/run/xyz123")  # alnum 但不是合法专利号
            self.assertEqual(r.status_code, 400)
            self.assertIn("Invalid patent publication number", r.json()["detail"])
            mocked_run.assert_not_called()

    def test_valid_pub_is_normalized_and_started(self) -> None:
        """小写 + "-" 分隔的合法号应被规范化后启动，而不是 reject。"""
        from fastapi.testclient import TestClient

        from patentradar.server import app as app_module

        with mock.patch.object(app_module, "run_pipeline") as mocked_run, \
             mock.patch.object(app_module, "is_run_in_progress", return_value=False):
            client = TestClient(app_module.app)
            r = client.post("/api/run/cn-114512759-a")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["publication_no"], "CN114512759A")


if __name__ == "__main__":
    unittest.main()
