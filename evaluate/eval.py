"""黄金集召回评估：系统跑出的 top_competitors 是否命中"已认定侵权竞品"。

口径（与用户对齐）：
- 命中 = 真竞品出现在 top_competitors（top5）里，不卡名次也不卡判定
- 纯关键词匹配；存疑行标 NEEDS_REVIEW 交人工复核

用法：
    uv run python evaluate/eval.py
产出：
    evaluate/eval_result.csv   逐条命中明细（供人工复核）
    控制台                      汇总指标
"""

from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
GOLD_XLSX = ROOT / "测试集.xlsx"
OUT_CSV = ROOT / "eval_result.csv"

# 规格/通用词，不作为型号 token（大写比较）
STOP_ALNUM = {
    "LFP", "NCM", "LMFP", "ECVT", "PHEV", "BEV", "EV", "AH", "WH", "MM",
    "KW", "KWH", "DC", "AC", "ID",
}
# 描述里的噪音中文词，清洗掉再抽品牌
NOISE_CN = [
    "中版", "纯电动", "增程式", "插电混动", "四驱", "两驱", "单速", "双电机",
    "六座版", "六座", "五座", "七座", "座版", "醇享版", "乾崑", "款", "版",
]


def _clean(desc: str) -> str:
    s = desc
    s = re.sub(r"（[^）]*）", " ", s)      # 去中文括号内容（规格）
    s = re.sub(r"\([^)]*\)", " ", s)       # 去英文括号内容
    s = re.sub(r"20\d{2}", " ", s)         # 去年份
    for w in NOISE_CN:
        s = s.replace(w, " ")
    return s


def extract_tokens(desc: str) -> tuple[str, set[str]]:
    """从竞品描述抽 (品牌主词, 型号 token 集)。"""
    s = _clean(desc)
    # 品牌核心词：第一段连续中文取前 2 字（"皇发鱼眼圆"→"皇发"、"岚图知音"→"岚图"），
    # 整词包含匹配太严会假漏，前 2 字 + 型号 token 双约束足够稳。
    brand = ""
    for seg in re.split(r"[\s/、,，;；]+", s):
        m = re.search(r"[一-鿿]{2,5}", seg)
        if m:
            brand = m.group(0)[:2]
            break
    # 型号 token：字母(+数字+连字符)组合，length>=2，去停用
    models: set[str] = set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", s):
        up = tok.upper()
        if len(tok) >= 2 and up not in STOP_ALNUM:
            models.add(up)
    return brand, models


def load_gold() -> dict[str, list[str]]:
    wb = openpyxl.load_workbook(GOLD_XLSX)
    ws = wb["Sheet1"]
    agg: dict[str, list[str]] = collections.defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        pub, comp = row[1], row[2]
        if not pub or not comp:
            continue
        # 分号 = 同一行多个竞品
        for part in re.split(r"[;；]", str(comp)):
            part = part.strip()
            if part:
                agg[str(pub).strip()].append(part)
    return agg


def candidate_haystack(cand: dict) -> str:
    c = cand.get("candidate", cand)
    fields = [
        c.get("company", ""), c.get("company_en", ""),
        c.get("product_name", ""), c.get("product_name_en", ""),
        c.get("product_intro", ""),
    ]
    return " ".join(str(f) for f in fields).upper()


def match_one(brand: str, models: set[str], hay: str) -> str:
    """返回 HIT / REVIEW / MISS。hay 已大写。"""
    brand_hit = bool(brand) and brand in hay
    model_hit = any(m in hay for m in models) if models else None

    if models:
        if brand_hit and model_hit:
            return "HIT"
        if brand_hit or model_hit:
            return "REVIEW"
        return "MISS"
    # 纯品牌竞品（无型号 token）
    if brand_hit:
        return "HIT"
    return "MISS"


def score_rank(cand: dict, tops: list[dict]) -> int:
    """按 total_score 的并列排名：仅严格高分者占先，同分并列同名次。
    例：top5 同分则都算第 1。"""
    s = float(cand.get("total_score") or 0)
    return 1 + sum(1 for o in tops if float(o.get("total_score") or 0) > s)


def claim1_status(cand: dict) -> str:
    for cmp in cand.get("comparisons", []):
        if str(cmp.get("feature_id", "")).startswith("C1-F1"):
            return cmp.get("status", "")
    return ""


def eval_pub(pub: str, golds: list[str]) -> list[dict]:
    out_dir = ROOT / pub / "module_2" / "top_competitors.json"
    rows = []
    if not out_dir.exists():
        for g in golds:
            rows.append({
                "publication_no": pub, "ran": "NO", "gold_competitor": g,
                "label": "NOT_RUN", "rank": "", "matched_candidate": "",
                "claim1": "", "note": "无结果目录",
            })
        return rows

    data = json.loads(out_dir.read_text(encoding="utf-8"))
    tops = data.get("top_competitors", [])
    excluded = data.get("excluded_candidates", [])

    for g in golds:
        brand, models = extract_tokens(g)
        best = {"label": "MISS", "rank": "", "cand": "", "claim1": "", "note": ""}

        # 先在 top_competitors 里找
        for cand in tops:
            hay = candidate_haystack(cand)
            label = match_one(brand, models, hay)
            if label in ("HIT", "REVIEW"):
                c = cand.get("candidate", {})
                best = {
                    "label": label, "rank": score_rank(cand, tops),
                    "cand": f"{c.get('company','')} {c.get('product_name','')}".strip(),
                    "claim1": claim1_status(cand),
                    "note": "",
                }
                if label == "HIT":
                    break  # HIT 优先，停止

        # top 里没命中 → 看是否被误杀（excluded）
        if best["label"] == "MISS":
            for cand in excluded:
                hay = candidate_haystack(cand)
                label = match_one(brand, models, hay)
                if label in ("HIT", "REVIEW"):
                    c = cand.get("candidate", {})
                    best = {
                        "label": "EXCLUDED_HIT" if label == "HIT" else "EXCLUDED_REVIEW",
                        "rank": "",
                        "cand": f"{c.get('company','')} {c.get('product_name','')}".strip(),
                        "claim1": claim1_status(cand),
                        "note": "真竞品被丢进 excluded（漏杀）",
                    }
                    break

        rows.append({
            "publication_no": pub, "ran": "YES", "gold_competitor": g,
            "label": best["label"], "rank": best["rank"],
            "matched_candidate": best["cand"], "claim1": best["claim1"],
            "brand_token": brand, "model_tokens": "|".join(sorted(models)),
            "note": best["note"],
        })
    return rows


DECIDE_THRESHOLD = 80.0  # 权1判定成立阈值：claim_1_score >= 80 视为落入保护范围


def decision_metrics(gold: dict[str, list[str]]) -> dict:
    """专利级权1判定：取该专利命中竞品的最高 claim_1_score，>= 阈值视为侵权成立。"""
    pub_scores = []  # 每个有命中的专利贡献一个最高分
    for pub, golds in gold.items():
        f = ROOT / pub / "module_3" / "full_claim_chart.json"
        if not f.exists():
            continue
        tops = json.loads(f.read_text(encoding="utf-8")).get("top_competitors", [])
        scores = []
        for g in golds:
            brand, models = extract_tokens(g)
            for c in tops:
                if match_one(brand, models, candidate_haystack(c)) in ("HIT", "REVIEW"):
                    scores.append(float(c.get("claim_1_score") or 0))
                    break
        if scores:
            pub_scores.append(max(scores))
    n = len(pub_scores)
    established = sum(1 for s in pub_scores if s >= DECIDE_THRESHOLD)
    return {
        "matched": n,
        "established": established,
        "rate": established / n if n else 0,
    }


def main() -> None:
    gold = load_gold()
    all_rows = []
    for pub in sorted(gold):
        all_rows.extend(eval_pub(pub, gold[pub]))

    cols = ["publication_no", "ran", "gold_competitor", "label", "rank",
            "matched_candidate", "claim1", "brand_token", "model_tokens", "note"]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    # ---- 专利级聚合：命中该专利任一竞品即算命中该专利 ----
    by_pub: dict[str, list[dict]] = collections.defaultdict(list)
    for r in all_rows:
        if r["ran"] == "YES":
            by_pub[r["publication_no"]].append(r)
    n = len(by_pub)

    hit1 = hit3 = hit5 = miss = 0
    mrr_sum = 0.0
    rank_dist: collections.Counter = collections.Counter()
    for pub, rows in by_pub.items():
        hit_ranks = [int(r["rank"]) for r in rows if r["label"] == "HIT" and r["rank"]]
        if hit_ranks:
            br = min(hit_ranks)  # 该专利最佳命中位次
            hit5 += 1
            rank_dist[br] += 1
            mrr_sum += 1 / br
            if br <= 3:
                hit3 += 1
            if br == 1:
                hit1 += 1
        else:
            miss += 1

    dm = decision_metrics(gold)
    not_run_pubs = len([p for p in gold if not (ROOT / p / "module_2" / "top_competitors.json").exists()])

    print(f"样本: 黄金集专利 {len(gold)} | 已跑 {n} | 未跑 {not_run_pubs}   (专利级口径)")
    print("=" * 52)
    print("【召回】命中 = 该专利任一真竞品进 Top-5；位次按 total_score 并列排名")
    print(f"  Hit@1 = {hit1}/{n} = {hit1/n:.1%}")
    print(f"  Hit@3 = {hit3}/{n} = {hit3/n:.1%}")
    print(f"  Hit@5 = {hit5}/{n} = {hit5/n:.1%}")
    print(f"  MRR   = {mrr_sum/n:.3f}")
    print(f"  位次分布: {dict(sorted(rank_dist.items()))}")
    print(f"  未命中专利: {miss}")
    print("=" * 52)
    print(f"【判定】权1成立(claim_1_score >= {DECIDE_THRESHOLD:.0f})")
    print(f"  成立率 = {dm['established']}/{dm['matched']} = {dm['rate']:.1%}")
    print("=" * 52)
    print(f"明细: {OUT_CSV}")


if __name__ == "__main__":
    main()
