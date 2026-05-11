"""Similar-patent deep link for module four.

When the infringement-risk threshold is hit (max_total_score >= 80), we
generate a Google Patents Advanced Search URL using ONLY Google's accepted
top-level URL params (confirmed by inspecting the URLs Google's own UI emits):

- `q="<title>"`         — exact title phrase
- `assignee=<applicant>` — exact applicant (note: NOT `inassignee=`, which
                           Google silently drops)
- `country=<CC>`        — same country code as the source patent
- `dups=language`       — turns family deduplication off so continuation
                           and divisional siblings show up (this is the
                           param value behind the "Publication number"
                           Duplicates dropdown option; other values like
                           `publication` are silently ignored)

We do NOT crawl Google Patents from Python — its xhr/query endpoint
aggressively rate-limits (HTTP 503). The reviewer opens the link in a
browser instead.
"""

from __future__ import annotations

import urllib.parse

from patentradar.schemas import SimilarPatentSearchHint, TaskPackage

INFRINGEMENT_RISK_THRESHOLD = 80.0


def build_similar_patent_hint(
    *,
    task_package: TaskPackage,
    triggered_by_score: float,
) -> SimilarPatentSearchHint:
    country = task_package.patent.country_code
    applicant = task_package.patent.applicants[0] if task_package.patent.applicants else ""
    title = task_package.patent.title or ""
    return SimilarPatentSearchHint(
        source_publication_no=task_package.patent.publication_no,
        triggered_by_total_score=triggered_by_score,
        threshold=INFRINGEMENT_RISK_THRESHOLD,
        country_code=country,
        applicant=applicant,
        title=title,
        google_patents_search_url=_build_url(country=country, applicant=applicant, title=title),
    )


def _build_url(*, country: str, applicant: str, title: str) -> str:
    params: list[tuple[str, str]] = []
    if title:
        params.append(("q", f'"{title}"'))
    if applicant:
        params.append(("assignee", applicant))
    if country:
        params.append(("country", country))
    params.append(("dups", "language"))
    return "https://patents.google.com/?" + urllib.parse.urlencode(params)
