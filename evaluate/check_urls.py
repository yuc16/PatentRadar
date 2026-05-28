"""证据 URL 可达率检测：遍历所有 module_2/3 的 evidence url，并发 HTTP 探测。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def collect_urls() -> set[str]:
    urls: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "url" and isinstance(v, str) and v.startswith("http"):
                    urls.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for pub_dir in ROOT.iterdir():
        if not pub_dir.is_dir():
            continue
        for mod in ["module_2/top_competitors.json", "module_3/full_claim_chart.json"]:
            f = pub_dir / mod
            if f.exists():
                walk(json.loads(f.read_text(encoding="utf-8")))
    return urls


def probe(url: str) -> tuple[str, bool, str]:
    headers = {"User-Agent": UA}
    try:
        with httpx.Client(timeout=10, follow_redirects=True, verify=False, headers=headers) as c:
            r = c.head(url)
            if r.status_code >= 400:
                r = c.get(url)  # 有些站不支持 HEAD
            ok = r.status_code < 400
            return url, ok, str(r.status_code)
    except Exception as e:  # noqa: BLE001
        return url, False, type(e).__name__


def main() -> None:
    urls = sorted(collect_urls())
    print(f"探测 {len(urls)} 个唯一 URL ...")
    results = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        for i, res in enumerate(ex.map(probe, urls), 1):
            results.append(res)
            if i % 50 == 0:
                print(f"  {i}/{len(urls)}")

    ok = sum(1 for _, k, _ in results if k)
    n = len(results)
    out = {
        "total": n,
        "reachable": ok,
        "unreachable": n - ok,
        "rate": round(ok / n, 4) if n else 0,
        "failures": [(u, s) for u, k, s in results if not k],
    }
    (ROOT / "url_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n可达率: {ok}/{n} = {ok/n:.1%}")
    print(f"明细写入 {ROOT/'url_check.json'}")


if __name__ == "__main__":
    main()
