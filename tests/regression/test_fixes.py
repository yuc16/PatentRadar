"""Regression tests for code-review fixes (no network / no LLM).

Each test pins one previously-shipped bug so the same regression can't sneak
back in. Keep these focused and fast.
"""

from __future__ import annotations

import json
import tempfile
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

        # mock 掉 run_and_release 防止真启动 BackgroundTask；通过断言它未被调用
        # 间接验证入口同步 reject。
        with mock.patch.object(app_module, "run_and_release") as mocked_run:
            client = TestClient(app_module.app)
            r = client.post("/api/run/xyz123")  # alnum 但不是合法专利号
            self.assertEqual(r.status_code, 400)
            self.assertIn("Invalid patent publication number", r.json()["detail"])
            mocked_run.assert_not_called()

    def test_valid_pub_is_normalized_and_started(self) -> None:
        """小写 + "-" 分隔的合法号应被规范化后启动，而不是 reject。"""
        from fastapi.testclient import TestClient

        from patentradar.server import app as app_module

        with mock.patch.object(app_module, "run_and_release"), \
             mock.patch.object(app_module, "try_begin_run", return_value=True):
            client = TestClient(app_module.app)
            r = client.post("/api/run/cn-114512759-a")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["publication_no"], "CN114512759A")


class EmptyEvidenceDowngradesStatusTest(unittest.TestCase):
    """Bug C1（codex 复审 #3）：FeatureComparison 旧版只按 status 硬写 score，
    不要求「明确满足/可能满足」必须有 evidence。导致 status=明确满足 + evidence=[]
    照样 score=1.0，零证据拿满分，违反可复核原则。修复后空证据降级到证据不足。"""

    def test_satisfied_without_evidence_is_downgraded(self) -> None:
        from patentradar.schemas import FeatureComparison

        cmp = FeatureComparison(
            feature_id="C1-F1", patent_feature="x", competitor_feature="y",
            status="明确满足", score=1.0, evidence=[], reasoning="r",
        )
        self.assertEqual(cmp.status, "证据不足")
        self.assertEqual(cmp.score, 0.3)

    def test_satisfied_with_evidence_keeps_full_score(self) -> None:
        from patentradar.schemas import EvidenceSource, FeatureComparison

        cmp = FeatureComparison(
            feature_id="C1-F1", patent_feature="x", competitor_feature="y",
            status="明确满足", score=1.0,
            evidence=[EvidenceSource(url="https://e.com/a")], reasoning="r",
        )
        self.assertEqual(cmp.status, "明确满足")
        self.assertEqual(cmp.score, 1.0)


class CanonicalizeClaimChartsTest(unittest.TestCase):
    """Bug C2（codex 复审 #2，两轮）：模块三若只补缺失项、不去重，LLM 仍能靠
    「重复满足特征」刷分——重复 10 次 C1-F1 + 漏 C1-F2 → (10×1.0+0.3)/11≈93.6，
    正确应为 (1.0+0.3)/2=65。修复后 _canonicalize_claim_charts 把 claim_charts
    重整成与 task_package 权威集合一一对应：去重特征、丢未知项、补漏判、去重 claim。"""

    def _task_package_3features(self):
        from patentradar.schemas import (
            Claim, ClaimFeature, PatentInfo, TaskPackage,
        )

        patent = PatentInfo(
            publication_no="CN999999A", title="t", applicants=["A"],
            google_patents_url="https://patents.google.com/patent/CN999999A",
            fetched_at="2026-01-01T00:00:00+08:00",
        )
        claim_1 = Claim(
            claim_no=1, claim_text="一种方法",
            features=[
                ClaimFeature(feature_id="C1-F1", feature_text="步骤A"),
                ClaimFeature(feature_id="C1-F2", feature_text="步骤B"),
                ClaimFeature(feature_id="C1-F3", feature_text="步骤C"),
            ],
        )
        return TaskPackage(
            patent=patent, technology_tag="其他", claims=[claim_1],
            claim_1_text=claim_1.claim_text, claim_1_features=claim_1.features,
            claims_source="html", model="test", reasoning_effort="medium",
        )

    def _satisfied_cmp(self, fid):
        return {
            "feature_id": fid, "patent_feature": "x",
            "status": "明确满足", "score": 1.0,
            "evidence": [{"url": "https://e.com", "title": "",
                          "source_name": "", "snippet": ""}],
            "reasoning": "r",
        }

    def test_missing_features_filled_as_insufficient(self) -> None:
        from patentradar.llm.workers.full_claim_chart_worker import (
            _canonicalize_claim_charts,
        )

        tp = self._task_package_3features()
        payload = {
            "claim_charts": [
                {
                    "claim_no": 1, "claim_text": "一种方法",
                    "comparisons": [self._satisfied_cmp("C1-F1")],
                    "claim_score": 100.0,
                }
            ]
        }
        _canonicalize_claim_charts(payload, tp)

        cmps = payload["claim_charts"][0]["comparisons"]
        self.assertEqual(len(cmps), 3, "缺失特征未补齐")
        by_id = {c["feature_id"]: c for c in cmps}
        self.assertEqual(by_id["C1-F2"]["status"], "证据不足")
        self.assertEqual(by_id["C1-F3"]["status"], "证据不足")

    def test_duplicate_features_are_deduped(self) -> None:
        from patentradar.llm.workers.full_claim_chart_worker import (
            _canonicalize_claim_charts,
        )
        from patentradar.schemas import FullClaimChartCandidate

        tp = self._task_package_3features()
        # 刷分场景：重复 10 次满足的 C1-F1、漏 C1-F2/F3
        payload = {
            "candidate": {
                "candidate_id": "P01", "company": "X", "company_en": "",
                "product_name": "Y", "product_name_en": "", "product_version": "v1",
                "market": "zh", "reason_for_deep_dive": "t",
                "source_result_ids": [], "source_urls": [],
                "initial_evidence_summary": "t",
            },
            "launch_date": "", "launch_date_evidence": [],
            "disqualified": False, "disqualification_reason": "",
            "claim_charts": [
                {
                    "claim_no": 1, "claim_text": "一种方法",
                    "comparisons": [self._satisfied_cmp("C1-F1") for _ in range(10)]
                    + [self._satisfied_cmp("C9-F9")],  # 还塞了一个未知特征
                    "claim_score": 100.0,
                },
                {  # 重复 claim 1，应被丢弃
                    "claim_no": 1, "claim_text": "一种方法",
                    "comparisons": [self._satisfied_cmp("C1-F1")],
                    "claim_score": 100.0,
                },
            ],
            "claim_1_score": 100.0, "total_score": 100.0,
            "searched_queries": [], "searched_providers": [],
        }
        _canonicalize_claim_charts(payload, tp)

        self.assertEqual(len(payload["claim_charts"]), 1, "重复 claim 未去重")
        cmps = payload["claim_charts"][0]["comparisons"]
        self.assertEqual(len(cmps), 3, "应恰好等于权威特征数")
        fids = sorted(c["feature_id"] for c in cmps)
        self.assertEqual(fids, ["C1-F1", "C1-F2", "C1-F3"], "未知特征未剔除/缺失未补")

        # 端到端分数：F1 满足(1.0) + F2/F3 证据不足(0.3) → (1+0.3+0.3)/3 ≈ 53.33
        cand = FullClaimChartCandidate.model_validate(payload)
        self.assertAlmostEqual(cand.claim_charts[0].claim_score, 53.33, places=1)

    def test_entirely_missing_claim_is_added(self) -> None:
        from patentradar.llm.workers.full_claim_chart_worker import (
            _canonicalize_claim_charts,
        )

        tp = self._task_package_3features()
        payload = {"claim_charts": []}  # LLM 整条 claim 都漏了
        _canonicalize_claim_charts(payload, tp)
        self.assertEqual(len(payload["claim_charts"]), 1)
        self.assertEqual(payload["claim_charts"][0]["claim_no"], 1)
        self.assertEqual(len(payload["claim_charts"][0]["comparisons"]), 3)


class RouterSkipsUnavailableProviderTest(unittest.TestCase):
    """Bug C3（codex 复审 #6）：未配置 key 的 provider（search() 返回 []）
    旧版照样占 max_providers_per_query 名额，排在前面就把唯一配好的挤掉。
    修复后未配置 provider 不计名额。"""

    def _fake_provider_cls(self):
        from patentradar.schemas import SearchResult
        from patentradar.search.base import SearchProvider

        class _Fake(SearchProvider):
            def __init__(self, name, available, results=None):
                self.name = name
                self._available = available
                self._results = results or []
                self.calls = 0

            @property
            def available(self):
                return self._available

            def search(self, *, query_id, query, max_results=5):
                self.calls += 1
                return self._results

        return _Fake, SearchResult

    def test_unavailable_providers_do_not_eat_budget(self) -> None:
        from patentradar.schemas import (
            ApplicantSelfSignals, QueryPlan, SearchQuery,
        )
        from patentradar.search.router import SearchRouter

        Fake, SearchResult = self._fake_provider_cls()
        brave_hit = SearchResult(
            result_id="brave-Q01-01", query_id="Q01", query="q",
            provider="brave", title="t", url="https://e.com/x",
            snippet="s", published_date="", rank=1,
        )
        t = Fake("tavily", available=False)
        b = Fake("bocha", available=False)
        e = Fake("exa", available=False)
        brave = Fake("brave", available=True, results=[brave_hit])
        router = SearchRouter(providers=[t, b, e, brave])

        plan = QueryPlan(
            publication_no="CN999999A", claim_1_summary="t",
            applicant_self_signals=ApplicantSelfSignals(),
            queries=[  # QueryPlan 要求 30-50 条
                SearchQuery(
                    query_id=f"Q{i:02d}", query=f"查询词{i}", intent="evidence",
                    language="mixed", target_feature_ids=[],
                    preferred_providers=["tavily", "bocha", "exa", "brave"],
                )
                for i in range(1, 31)
            ],
        )
        artifact = router.search_query_plan(
            publication_no="CN999999A", query_plan=plan,
            max_providers_per_query=3,
        )
        # 未配置 provider 一次都不该被调用，也不占名额，所以排第 4 的 brave 每条
        # query 都能跑到（30 条）。修复前 max=3 会被前三个未配置 provider 占满，
        # brave.calls 恒为 0。
        self.assertEqual(t.calls, 0)
        self.assertEqual(b.calls, 0)
        self.assertEqual(e.calls, 0)
        self.assertEqual(brave.calls, 30, "唯一配好的 brave 被未配置 provider 挤掉了")
        self.assertTrue(any(r.url == "https://e.com/x" for r in artifact.results))


class SsrfGuardTest(unittest.TestCase):
    """Bug C4（codex 复审 #4）：抓取器直接请求 LLM/搜索/页面给的 URL，不挡
    内网 / 回环 / 云元数据地址。修复后 _is_safe_url 拦截这些目标。"""

    def test_blocks_private_loopback_and_metadata(self) -> None:
        from patentradar.fetcher.web_fetcher import _is_safe_url

        for url in (
            "http://127.0.0.1/",
            "http://localhost/",  # 解析到回环
            "http://169.254.169.254/latest/meta-data/",  # 云元数据
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://100.64.0.1/",  # CGNAT 100.64.0.0/10，is_private 不覆盖
            "http://[::1]/",
            "ftp://example.com/",  # 非 http(s)
            "file:///etc/passwd",
        ):
            self.assertFalse(_is_safe_url(url), f"应拦截 {url}")

    def test_allows_public_ip(self) -> None:
        from patentradar.fetcher.web_fetcher import _is_safe_url

        # 用字面公网 IP 避免依赖 DNS / 网络
        self.assertTrue(_is_safe_url("https://8.8.8.8/"))


class RenderMarkdownSanitizesXssTest(unittest.TestCase):
    """Bug C5（codex 复审 #5）：/api/render 把 LLM markdown 渲染的原始 HTML
    直接嵌进同源 HTMLResponse → 存储型 XSS。修复后 nh3 消毒剥离 script。"""

    def test_script_is_stripped_from_rendered_report(self) -> None:
        from fastapi.testclient import TestClient

        from patentradar.server import app as app_module

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            pub_dir = data_root / "CN999999A"
            pub_dir.mkdir()
            (pub_dir / "report.md").write_text(
                "# 报告\n\n正常内容\n\n<script>alert(1)</script>\n",
                encoding="utf-8",
            )
            with mock.patch.object(app_module, "DATA_OUTPUT", data_root):
                client = TestClient(app_module.app)
                r = client.get("/api/render/CN999999A/report.md")
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("<script>", r.text)
                self.assertNotIn("alert(1)", r.text)
                self.assertIn("正常内容", r.text)


class StartRunIsAtomicTest(unittest.TestCase):
    """Bug C6（codex 复审 #8）：POST /api/run 旧版「is_run_in_progress 检查 +
    后台 acquire」非原子，两个并发请求都能返回 started。修复后入口同步 acquire，
    第二次直接 409。"""

    def test_second_concurrent_run_gets_409(self) -> None:
        from fastapi.testclient import TestClient

        from patentradar.server import app as app_module
        from patentradar.server import runner

        pub = "CN888888A"
        # mock run_and_release 让后台任务不真跑（也就不释放锁），模拟"第一个还在跑"
        with mock.patch.object(app_module, "run_and_release"):
            client = TestClient(app_module.app)
            try:
                r1 = client.post(f"/api/run/{pub}")
                self.assertEqual(r1.status_code, 200)
                r2 = client.post(f"/api/run/{pub}")
                self.assertEqual(r2.status_code, 409)
            finally:
                with runner._locks_guard:
                    runner._in_progress.pop(pub, None)


class PdfUrlFetcherBlocksInternalTest(unittest.TestCase):
    """Bug C7（codex 复审 #3）：report.md→PDF 旧版把原始 HTML 直接交给
    WeasyPrint，<img src=内网> 会被服务端抓取（SSRF）。修复后自定义 url_fetcher
    拒绝内网资源、放行 data:。"""

    def test_internal_resource_url_is_blocked(self) -> None:
        from patentradar.modules.report.pipeline import _safe_pdf_url_fetcher

        for url in (
            "http://127.0.0.1:8000/secret",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ):
            with self.assertRaises(ValueError):
                _safe_pdf_url_fetcher(url)

    def test_data_uri_is_allowed(self) -> None:
        from patentradar.modules.report.pipeline import _safe_pdf_url_fetcher

        # 1x1 透明 PNG 的 data URI：应被放行（default_url_fetcher 能解析）
        result = _safe_pdf_url_fetcher(
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
        )
        self.assertIn("string", result)


class EvidencePoolValidationTest(unittest.TestCase):
    """Bug C8（codex 复审 #6）：evidence 旧版只校验 URL 合法，不核对是否来自该
    候选实际抓取的证据池，任意虚构 URL 仍能拿满分。修复后 allowed_urls 之外的
    evidence 被剔除，随之降级证据不足。"""

    def test_module2_fabricated_url_is_dropped(self) -> None:
        from patentradar.llm.workers.evidence_worker import _drop_empty_url_evidence

        payload = {
            "results": [
                {
                    "candidate": {"candidate_id": "P01"},
                    "comparisons": [
                        {
                            "feature_id": "C1-F1", "status": "明确满足", "score": 1.0,
                            "evidence": [
                                {"url": "https://real.com/page", "title": "",
                                 "source_name": "", "snippet": ""},
                                {"url": "https://fabricated.com/made-up", "title": "",
                                 "source_name": "", "snippet": ""},
                            ],
                            "reasoning": "r",
                        }
                    ],
                    "launch_date_evidence": [],
                }
            ]
        }
        _drop_empty_url_evidence(
            payload,
            allowed_urls_by_candidate={"P01": {"https://real.com/page"}},
        )
        evid = payload["results"][0]["comparisons"][0]["evidence"]
        urls = [e["url"] for e in evid]
        self.assertIn("https://real.com/page", urls)
        self.assertNotIn("https://fabricated.com/made-up", urls, "编造 URL 未被剔除")

    def test_module2_all_fabricated_downgrades_status(self) -> None:
        from patentradar.llm.workers.evidence_worker import _drop_empty_url_evidence

        payload = {
            "results": [
                {
                    "candidate": {"candidate_id": "P01"},
                    "comparisons": [
                        {
                            "feature_id": "C1-F1", "status": "明确满足", "score": 1.0,
                            "evidence": [
                                {"url": "https://fabricated.com/x", "title": "",
                                 "source_name": "", "snippet": ""},
                            ],
                            "reasoning": "r",
                        }
                    ],
                    "launch_date_evidence": [],
                }
            ]
        }
        _drop_empty_url_evidence(
            payload,
            allowed_urls_by_candidate={"P01": {"https://real.com/page"}},
        )
        cmp = payload["results"][0]["comparisons"][0]
        self.assertEqual(cmp["evidence"], [])
        self.assertEqual(cmp["status"], "证据不足", "全编造 URL 应降级")

    def test_module3_fabricated_url_is_dropped(self) -> None:
        from patentradar.llm.workers.full_claim_chart_worker import (
            _drop_empty_url_evidence,
        )

        payload = {
            "claim_charts": [
                {
                    "comparisons": [
                        {
                            "feature_id": "C1-F1", "status": "明确满足", "score": 1.0,
                            "evidence": [
                                {"url": "https://real.com/p", "title": "",
                                 "source_name": "", "snippet": ""},
                                {"url": "https://fake.com/x", "title": "",
                                 "source_name": "", "snippet": ""},
                            ],
                            "reasoning": "r",
                        }
                    ]
                }
            ],
            "launch_date_evidence": [],
        }
        _drop_empty_url_evidence(payload, allowed_urls={"https://real.com/p"})
        urls = [e["url"] for e in payload["claim_charts"][0]["comparisons"][0]["evidence"]]
        self.assertEqual(urls, ["https://real.com/p"])


class ReplayExportSanitizesXssTest(unittest.TestCase):
    """Bug C9（codex 复审 #5）：/api/render 已消毒，但离线回放导出路径仍把
    LLM markdown 原始 HTML 写进回放文件，点开即执行。修复后导出同样 nh3 消毒。"""

    def test_exported_md_html_has_no_script(self) -> None:
        from patentradar.server import app as app_module

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            pub = "CN999999A"
            (data_root / pub).mkdir()
            (data_root / pub / "report.md").write_text(
                "# 报告\n\n正常内容\n\n<script>alert(1)</script>\n",
                encoding="utf-8",
            )
            summary = {4: {"files": [{"name": "report.md", "kind": "md"}]}}
            with mock.patch.object(app_module, "DATA_OUTPUT", data_root), \
                 mock.patch.object(
                     app_module, "_module_output_summary", return_value=summary
                 ):
                outputs = app_module._collect_export_outputs(pub)

        md_entries = [o for o in outputs if o.get("kind") == "md"]
        self.assertTrue(md_entries, "未收集到 md 产物")
        html = md_entries[0]["html"]
        self.assertNotIn("<script>", html)
        self.assertNotIn("alert(1)", html)
        self.assertIn("正常内容", html)


class UnsupportedNegativeIsDowngradedTest(unittest.TestCase):
    """Bug C10（codex 复审三 P1-1）：可复核原则只对正向状态生效，无证据的
    「明确不满足」仍会触发失格清零，等于凭空淘汰候选。修复后负向无证据也降级
    「证据不足」。"""

    def _cand(self):
        from patentradar.schemas import Candidate

        return Candidate(
            candidate_id="P01", company="X", product_name="Y", market="zh",
            reason_for_deep_dive="t", initial_evidence_summary="t",
        )

    def test_unsatisfied_without_evidence_downgraded(self) -> None:
        from patentradar.schemas import FeatureComparison

        cmp = FeatureComparison(
            feature_id="C1-F1", patent_feature="x", status="明确不满足",
            score=0.0, evidence=[], reasoning="r",
        )
        self.assertEqual(cmp.status, "证据不足")
        self.assertEqual(cmp.score, 0.3)

    def test_candidate_not_disqualified_by_unsupported_negative(self) -> None:
        from patentradar.schemas import CandidateEvidence, FeatureComparison

        ce = CandidateEvidence(
            candidate=self._cand(),
            comparisons=[
                FeatureComparison(
                    feature_id="C1-F1", patent_feature="x", status="明确不满足",
                    score=0.0, evidence=[], reasoning="r",
                )
            ],
            total_score=0.0,
        )
        self.assertFalse(ce.disqualified, "无证据的明确不满足不应失格")
        self.assertAlmostEqual(ce.total_score, 30.0, places=1)  # 证据不足 0.3 → 30

    def test_evidence_backed_negative_still_disqualifies(self) -> None:
        from patentradar.schemas import (
            CandidateEvidence, EvidenceSource, FeatureComparison,
        )

        ce = CandidateEvidence(
            candidate=self._cand(),
            comparisons=[
                FeatureComparison(
                    feature_id="C1-F1", patent_feature="x", status="明确不满足",
                    score=0.0, evidence=[EvidenceSource(url="https://e.com/a")],
                    reasoning="r",
                )
            ],
            total_score=0.0,
        )
        self.assertTrue(ce.disqualified, "带证据的明确不满足仍应失格")


class DeterministicDisqualificationTest(unittest.TestCase):
    """Bug C11（codex 复审三 P1-2 + 复审四 P1）：失格不能信任 LLM 的 disqualified。
    _normalize_batch 改为代码裁定——只认「带证据的明确不满足」或「年份可考证早于
    申请日的上市日期」。任意晚于申请日的有效 URL、或凭空 disqualified=True 都应
    被纠正为不失格；无证据的明确不满足经降级后也不再失格（完整 worker 路径）。"""

    def _task_package(self, application_date="2020-01-01"):
        from patentradar.schemas import (
            Claim, ClaimFeature, PatentInfo, TaskPackage,
        )

        patent = PatentInfo(
            publication_no="CN999999A", title="t", applicants=["A"],
            application_date=application_date,
            google_patents_url="https://patents.google.com/patent/CN999999A",
            fetched_at="2026-01-01T00:00:00+08:00",
        )
        claim_1 = Claim(
            claim_no=1, claim_text="一种方法",
            features=[ClaimFeature(feature_id="C1-F1", feature_text="步骤A")],
        )
        return TaskPackage(
            patent=patent, technology_tag="其他", claims=[claim_1],
            claim_1_text=claim_1.claim_text, claim_1_features=claim_1.features,
            claims_source="html", model="test", reasoning_effort="medium",
        )

    def _candidate(self):
        from patentradar.schemas import Candidate

        return Candidate(
            candidate_id="P01", company="X", product_name="Y", market="zh",
            reason_for_deep_dive="t", initial_evidence_summary="t",
        )

    def _run_normalize(self, *, status, evidence_url, launch_date, launch_evidence,
                       llm_disqualified, application_date="2020-01-01"):
        from patentradar.llm.workers.evidence_worker import _normalize_batch
        from patentradar.schemas import (
            CandidateEvidence, EvidenceBatchResult, EvidenceSource, FeatureComparison,
        )

        ev = [EvidenceSource(url=u) for u in ([evidence_url] if evidence_url else [])]
        led = [EvidenceSource(url=u) for u in ([launch_evidence] if launch_evidence else [])]
        ce = CandidateEvidence(
            candidate=self._candidate(),
            launch_date=launch_date, launch_date_evidence=led,
            disqualified=llm_disqualified,
            disqualification_reason="LLM 自报" if llm_disqualified else "",
            comparisons=[
                FeatureComparison(
                    feature_id="C1-F1", patent_feature="步骤A", status=status,
                    score=0.0, evidence=ev, reasoning="r",
                )
            ],
            total_score=0.0,
        )
        batch = EvidenceBatchResult(
            publication_no="CN999999A", batch_id="b", results=[ce]
        )
        out = _normalize_batch(
            batch, task_package=self._task_package(application_date),
            candidates=[self._candidate()],
        )
        return out.results[0]

    def test_launch_after_filing_not_disqualified(self) -> None:
        # 有效 URL 但日期晚于申请日 + LLM 乱标 disqualified=True → 代码纠正为不失格
        r = self._run_normalize(
            status="明确满足", evidence_url="https://real.com/a",
            launch_date="2025年", launch_evidence="https://real.com/launch",
            llm_disqualified=True,
        )
        self.assertFalse(r.disqualified, "晚于申请日仍失格")
        self.assertGreater(r.total_score, 0)

    def test_launch_before_filing_disqualified(self) -> None:
        r = self._run_normalize(
            status="明确满足", evidence_url="https://real.com/a",
            launch_date="2018年Q2", launch_evidence="https://real.com/launch",
            llm_disqualified=False,
        )
        self.assertTrue(r.disqualified, "早于申请日应失格")
        self.assertEqual(r.total_score, 0.0)

    def test_evidence_backed_negative_disqualifies(self) -> None:
        r = self._run_normalize(
            status="明确不满足", evidence_url="https://real.com/a",
            launch_date="未明确", launch_evidence=None, llm_disqualified=False,
        )
        self.assertTrue(r.disqualified)

    def test_unsupported_negative_not_disqualified_full_path(self) -> None:
        # 从一开始就空证据的「明确不满足」：经 Pydantic 降级为证据不足 → 不失格
        r = self._run_normalize(
            status="明确不满足", evidence_url=None,
            launch_date="未明确", launch_evidence=None, llm_disqualified=True,
        )
        self.assertFalse(r.disqualified, "无证据负向经降级后不应失格")
        self.assertAlmostEqual(r.total_score, 30.0, places=1)  # 单特征证据不足 0.3

    def _m2_evidence(self, *, launch_date="未明确", launch_url=None, disqualified=False):
        from patentradar.schemas import CandidateEvidence, EvidenceSource

        led = [EvidenceSource(url=launch_url)] if launch_url else []
        return CandidateEvidence(
            candidate=self._candidate(), launch_date=launch_date,
            launch_date_evidence=led, disqualified=disqualified,
            comparisons=[], total_score=50.0,
        )

    def test_module3_ignores_llm_disqualified(self) -> None:
        """模块三不信任 LLM 自报的 disqualified：无 launch 证据 + 模块二未失格 →
        最终不失格。"""
        from patentradar.llm.workers.full_claim_chart_worker import (
            _apply_launch_disqualification,
        )

        payload = {"disqualified": True, "disqualification_reason": "LLM 乱标",
                   "launch_date": "未明确", "launch_date_evidence": [], "claim_charts": []}
        _apply_launch_disqualification(payload, self._task_package(), self._m2_evidence())
        self.assertFalse(payload["disqualified"], "模块三未忽略 LLM 自报失格")
        self.assertEqual(payload["disqualification_reason"], "")

    def test_module3_new_earlier_launch_disqualifies(self) -> None:
        """复审五 P1：模块三 round 2 拿到更早上市证据（2018 < 申请日 2020）应失格，
        即便模块二当时未失格。"""
        from patentradar.llm.workers.full_claim_chart_worker import (
            _apply_launch_disqualification,
        )

        payload = {
            "disqualified": False, "disqualification_reason": "",
            "launch_date": "2018年Q2",
            "launch_date_evidence": [{"url": "https://real.com/launch", "title": "",
                                      "source_name": "", "snippet": ""}],
            "claim_charts": [],
        }
        _apply_launch_disqualification(
            payload, self._task_package(application_date="2020-01-01"),
            self._m2_evidence(),  # 模块二未失格
        )
        self.assertTrue(payload["disqualified"], "模块三新证据更早上市未触发失格")
        self.assertIn("早于专利申请日", payload["disqualification_reason"])


class LockSetSemanticsTest(unittest.TestCase):
    """Bug C12（codex 复审三 P1-3）：per-pub Lock 字典 + locked() 自省存在 ABA
    竞态，两线程可拿到不同 Lock 都 acquire 成功 → 并发跑同一专利。修复后改成
    _locks_guard 保护的 token 表，占位/查询/释放原子完成。"""

    def test_try_begin_run_is_atomic_and_reusable(self) -> None:
        from patentradar.server import runner

        pub = "CN777777A"
        token = runner.try_begin_run(pub)
        try:
            self.assertIsNotNone(token)
            self.assertTrue(runner.is_run_in_progress(pub))
            self.assertIsNone(runner.try_begin_run(pub), "重复占位应失败")
        finally:
            runner._end_run(pub, token)
        self.assertFalse(runner.is_run_in_progress(pub))
        # 释放后可再次占用
        token2 = runner.try_begin_run(pub)
        self.assertIsNotNone(token2)
        runner._end_run(pub, token2)

    def test_end_run_requires_matching_token(self) -> None:
        """C12 P2（复审四）：没有持有预留 token 的误调用不能释放别人的槽位。"""
        from patentradar.server import runner

        pub = "CN666666A"
        token = runner.try_begin_run(pub)
        try:
            # 错误 token 不能释放
            runner._end_run(pub, "wrong-token")
            self.assertTrue(runner.is_run_in_progress(pub), "错误 token 竟释放了槽位")
            # 正确 token 才能释放
            runner._end_run(pub, token)
            self.assertFalse(runner.is_run_in_progress(pub))
        finally:
            with runner._locks_guard:
                runner._in_progress.pop(pub, None)

    def test_no_per_pub_lock_introspection_left(self) -> None:
        from patentradar.server import runner

        # 回归：旧的 _lock_for / _run_locks（ABA 根源）必须已移除
        self.assertFalse(hasattr(runner, "_lock_for"))
        self.assertFalse(hasattr(runner, "_run_locks"))


class Step4CacheVersioningTest(unittest.TestCase):
    """Bug C13（codex 复审三 P2）：step4 单候选缓存只做 Pydantic 校验，修复前写下
    的旧缓存（编造 URL、满分）仍能原样载入并被模块三纳入白名单。修复后缓存带
    版本号，旧扁平缓存一律失效重算。"""

    def _inputs(self):
        from patentradar.schemas import (
            ApplicantSelfSignals, Candidate, CandidateShortlist, Claim,
            ClaimFeature, PatentInfo, QueryPlan, SearchQuery, TaskPackage,
        )

        patent = PatentInfo(
            publication_no="CN999999A", title="t", applicants=["A"],
            google_patents_url="https://patents.google.com/patent/CN999999A",
            fetched_at="2026-01-01T00:00:00+08:00",
        )
        claim_1 = Claim(
            claim_no=1, claim_text="一种方法",
            features=[ClaimFeature(feature_id="C1-F1", feature_text="步骤A")],
        )
        tp = TaskPackage(
            patent=patent, technology_tag="其他", claims=[claim_1],
            claim_1_text=claim_1.claim_text, claim_1_features=claim_1.features,
            claims_source="html", model="test", reasoning_effort="medium",
        )
        cand = Candidate(
            candidate_id="P01", company="测试", product_name="产品", market="zh",
            reason_for_deep_dive="t", initial_evidence_summary="t",
        )
        shortlist = CandidateShortlist(publication_no="CN999999A", candidates=[cand])
        qp = QueryPlan(
            publication_no="CN999999A", claim_1_summary="t",
            applicant_self_signals=ApplicantSelfSignals(),
            queries=[
                SearchQuery(query_id=f"Q{i:02d}", query=f"q{i}q", intent="evidence",
                            language="zh", target_feature_ids=[], preferred_providers=[])
                for i in range(1, 31)
            ],
        )
        return tp, shortlist, qp, cand

    def _flat_evidence_dump(self, cand):
        from patentradar.schemas import CandidateEvidence, EvidenceSource, FeatureComparison

        ce = CandidateEvidence(
            candidate=cand, launch_date="2020", launch_date_evidence=[],
            comparisons=[
                FeatureComparison(
                    feature_id="C1-F1", patent_feature="步骤A", status="明确满足",
                    score=1.0, evidence=[EvidenceSource(url="https://cached.com/x")],
                    reasoning="r",
                )
            ],
            total_score=100.0,
        )
        return ce.model_dump()

    def test_old_flat_cache_is_ignored(self) -> None:
        from patentradar.modules.competitor_search import pipeline as m2

        tp, shortlist, qp, cand = self._inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cand_dir = out / "step4_candidates"
            cand_dir.mkdir()
            # 旧扁平缓存（无 _cache_version）
            (cand_dir / "P01.json").write_text(
                json.dumps(self._flat_evidence_dump(cand), ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(
                m2, "map_evidence_for_batch", side_effect=RuntimeError("must recompute")
            ) as mocked:
                m2.run_step4_map_evidence(
                    task_package=tp, shortlist=shortlist, output_dir=out,
                    query_plan=qp, max_workers=1,
                )
            mocked.assert_called()  # 旧扁平缓存应被忽略并重新计算

    def test_versioned_cache_is_loaded(self) -> None:
        from patentradar.modules.competitor_search import pipeline as m2

        tp, shortlist, qp, cand = self._inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cand_dir = out / "step4_candidates"
            cand_dir.mkdir()
            (cand_dir / "P01.json").write_text(
                json.dumps(
                    {"_cache_version": m2._STEP4_CACHE_VERSION,
                     "evidence": self._flat_evidence_dump(cand)},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                m2, "map_evidence_for_batch", side_effect=RuntimeError("should not run")
            ) as mocked:
                results = m2.run_step4_map_evidence(
                    task_package=tp, shortlist=shortlist, output_dir=out,
                    query_plan=qp, max_workers=1,
                )
            mocked.assert_not_called()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].total_score, 100.0)


class PipelineVersionInvalidatesCacheTest(unittest.TestCase):
    """Bug C14（codex 复审四 P2）：_is_fully_cached 只看产物齐全 + pipeline_end ok，
    旧版本跑完的专利会被整条复用，step4 缓存版本号根本没机会检查。修复后完成 run
    必须带当前 PIPELINE_VERSION 才算可复用。"""

    def _setup(self, tmp, pipeline_version):
        logs = Path(tmp) / "logs"
        data = Path(tmp) / "data"
        (logs / "CN1A").mkdir(parents=True)
        (data / "CN1A").mkdir(parents=True)
        end = {"event": "pipeline_end", "status": "ok"}
        if pipeline_version is not None:
            end["pipeline_version"] = pipeline_version
        (logs / "CN1A" / "run.jsonl").write_text(
            json.dumps(end) + "\n", encoding="utf-8"
        )
        for name in (
            "task_package.json", "step5_top5_claim1_candidates.json",
            "top5_full_claim_chart.json", "report.md",
        ):
            (data / "CN1A" / name).write_text("{}", encoding="utf-8")
        return logs, data

    def _check(self, pipeline_version):
        from patentradar.server import runner

        with tempfile.TemporaryDirectory() as tmp:
            logs, data = self._setup(tmp, pipeline_version)
            with mock.patch.object(runner, "LOGS_ROOT", logs), \
                 mock.patch.object(runner, "DATA_OUTPUT", data):
                return runner._is_fully_cached("CN1A")

    def test_old_version_not_fully_cached(self) -> None:
        self.assertFalse(self._check(1), "旧版本完成 run 不应被整条复用")

    def test_missing_version_not_fully_cached(self) -> None:
        self.assertFalse(self._check(None), "无版本标记的旧 run 不应被复用")

    def test_current_version_is_fully_cached(self) -> None:
        from patentradar.server import runner

        self.assertTrue(self._check(runner.PIPELINE_VERSION))


class LaunchDateComparisonTest(unittest.TestCase):
    """Bug C15（codex 复审五 P2）：上市日期只比年份，同年更早的会被漏判；多年份
    只取第一个会选错 SKU 年。修复后月份粒度 + 多年份保守不失格。"""

    def test_same_year_earlier_month_is_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        self.assertTrue(launch_before_application("2020年1月", "2020-12-01"))

    def test_same_year_later_month_not_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        self.assertFalse(launch_before_application("2020年12月", "2020-01-01"))

    def test_earlier_year_is_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        self.assertTrue(launch_before_application("2018年Q2", "2020-01-01"))

    def test_multiple_years_is_ambiguous_not_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        # 含糊（混了多个 SKU 年份）→ 保守不失格
        self.assertFalse(
            launch_before_application("OS6.1 2018年推送；OS6.2 2021年上线", "2020-01-01")
        )

    def test_same_year_unknown_month_not_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        # 同年但月份不可知 → 保守不失格
        self.assertFalse(launch_before_application("2020年", "2020-06-01"))

    def test_unparseable_application_date_not_before(self) -> None:
        from patentradar.core.launch_date import launch_before_application

        self.assertFalse(launch_before_application("2018年", ""))


class RunAndReleaseRejectsWrongTokenTest(unittest.TestCase):
    """Bug C16（codex 复审五 P2）：run_and_release 执行流水线前不校验 token，错误
    token 仍会进入执行逻辑，与真正持有者并发写同一日志/产物。修复后非持有者直接
    不执行。"""

    def test_wrong_token_does_not_run_pipeline(self) -> None:
        from patentradar.server import runner

        pub = "CN555555A"
        token = runner.try_begin_run(pub)
        try:
            with mock.patch.object(runner, "_run_pipeline_locked") as mocked_run:
                runner.run_and_release(pub, "stale-wrong-token")
                mocked_run.assert_not_called()  # 非持有者不得执行
                # 真正持有者仍在，槽位未被误释放
                self.assertTrue(runner.is_run_in_progress(pub))
                # 正确 token 才执行并释放
                runner.run_and_release(pub, token)
                mocked_run.assert_called_once()
            self.assertFalse(runner.is_run_in_progress(pub))
        finally:
            with runner._locks_guard:
                runner._in_progress.pop(pub, None)


if __name__ == "__main__":
    unittest.main()
