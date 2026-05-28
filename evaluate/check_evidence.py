"""证据真实性检测：证据 URL 的页面正文里，是否真的出现了它所对应竞品的
型号/品牌。命中 = 该 URL 确实在讲这个竞品（模型没乱给链接）。

口径：关键词溯源。对每个 candidate，从其 product_name / company 抽型号 token
(L600 / 196Ah / SU7 ...) 和品牌词；该候选下所有 evidence 的 url，抓页面正文后
检查这些标识是否出现。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

STOP_ALNUM = {
    "LFP", "NCM", "LMFP", "ECVT", "PHEV", "BEV", "EV", "AH", "WH", "MM",
    "KW", "KWH", "DC", "AC", "ID", "CO", "LTD", "INC",
}


def cand_tokens(cand: dict) -> set[str]:
    """从系统候选抽标识 token（大写）：品牌前 2 字 + 型号字母数字串。"""
    c = cand.get("candidate", cand)
    toks: set[str] = set()
    company = str(c.get("company", ""))
    m = re.search(r"[一-鿿]{2,}", company)
    if m:
        toks.add(m.group(0)[:2])  # 中文品牌核心
    text = " ".join(str(c.get(k, "")) for k in ("product_name", "product_name_en", "company_en"))
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", text):
        up = tok.upper()
        if up not in STOP_ALNUM and any(ch.isdigit() for ch in up) or (up not in STOP_ALNUM and len(up) <= 4):
            toks.add(up)
    return {t for t in toks if t}


def collect() -> dict[str, set[str]]:
    """{url: 关联候选的标识 token 集}。同一 url 多候选则合并。"""
    url_tokens: dict[str, set[str]] = defaultdict(set)
    for pub_dir in ROOT.iterdir():
        if not pub_dir.is_dir():
            continue
        for mod in ["module_2/top_competitors.json", "module_3/full_claim_chart.json"]:
            f = pub_dir / mod
            if not f.exists():
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            cands = data.get("top_competitors", []) + data.get("excluded_candidates", [])
            for cand in cands:
                toks = cand_tokens(cand)

                def grab(o):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if k == "url" and isinstance(v, str) and v.startswith("http"):
                                url_tokens[v] |= toks
                            else:
                                grab(v)
                    elif isinstance(o, list):
                        for x in o:
                            grab(x)

                grab(cand)
    return url_tokens


def probe(item: tuple[str, set[str]]) -> tuple[str, str]:
    """返回 (url, 结果)：HIT / MISS / SKIP(非html/抓不到)。"""
    url, toks = item
    if not toks:
        return url, "SKIP"
    headers = {"User-Agent": UA}
    try:
        with httpx.Client(timeout=12, follow_redirects=True, verify=False, headers=headers) as c:
            r = c.get(url)
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype.lower():
                return url, "SKIP"  # PDF / 图片等正文无法可靠抽取
            text = lxml_html.fromstring(r.text).text_content().upper()
    except Exception:  # noqa: BLE001
        return url, "SKIP"
    return url, ("HIT" if any(t in text for t in toks) else "MISS")


def main() -> None:
    url_tokens = collect()
    items = list(url_tokens.items())
    print(f"检测 {len(items)} 个证据 URL 的内容相关性 ...")
    results = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        for i, res in enumerate(ex.map(probe, items), 1):
            results.append(res)
            if i % 50 == 0:
                print(f"  {i}/{len(items)}")

    hit = sum(1 for _, s in results if s == "HIT")
    miss = sum(1 for _, s in results if s == "MISS")
    skip = sum(1 for _, s in results if s == "SKIP")
    judged = hit + miss
    out = {
        "total": len(results),
        "judged": judged,
        "hit": hit,
        "miss": miss,
        "skipped": skip,
        "relevance_rate": round(hit / judged, 4) if judged else 0,
        "misses": [u for u, s in results if s == "MISS"],
    }
    (ROOT / "evidence_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n可判定 {judged} 个（跳过 {skip}: 非HTML/抓不到）")
    print(f"证据相关率: {hit}/{judged} = {hit/judged:.1%}" if judged else "无可判定 URL")
    print(f"明细写入 {ROOT/'evidence_check.json'}")


if __name__ == "__main__":
    main()
