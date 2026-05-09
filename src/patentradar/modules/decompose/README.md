# Module One: decompose

`decompose` receives one patent publication number and produces `task_package.json`.

The module has two jobs:

1. Fetch complete patent bibliographic data and all claims from Google Patents.
2. Ask GPT-5.5 to decompose every claim into comparison-ready technical features.

## Inputs

Primary input:

```text
publication_no
```

Accepted formats include:

```text
CN105335144B
CN-105335144-B
CN 105335144 B
https://patents.google.com/patent/CN105335144B/zh
```

Runtime configuration comes from `.env` or process environment:

```env
PATENTRADAR_MODEL=gpt-5.5
PATENTRADAR_CONTEXT_LENGTH=258000
PATENTRADAR_REASONING_EFFORT=high
```

`PATENTRADAR_CONTEXT_LENGTH` is recorded as a project setting for later modules. Module one does not manually truncate context yet.

## Output

The output file is:

```text
task_package.json
```

Schema shape:

```json
{
  "patent": {
    "publication_no": "CN105335144B",
    "title": "...",
    "applicants": ["比亚迪股份有限公司"],
    "inventors": ["..."],
    "application_date": "YYYY-MM-DD",
    "google_patents_url": "https://patents.google.com/patent/CN105335144B/zh",
    "pdf_url": "https://...",
    "fetched_at": "..."
  },
  "technology_tag": "整车与车身底盘",
  "claims": [
    {
      "claim_no": 1,
      "claim_text": "完整权利要求原文",
      "features": [
        {
          "feature_id": "C1-F1",
          "feature_text": "原文连续片段"
        }
      ]
    }
  ],
  "claim_1_text": "由 claims 中 claim_no=1 强制派生",
  "claim_1_features": [
    {
      "feature_id": "C1-F1",
      "feature_text": "由 claims 中 claim_no=1 强制派生"
    }
  ],
  "claims_source": "html",
  "model": "gpt-5.5",
  "reasoning_effort": "high"
}
```

`claim_1_text` and `claim_1_features` are never trusted from the LLM response. They are always derived from `claims` where `claim_no == 1`.

## Technology Tags

`technology_tag` must be one of:

```text
动力电池
电驱系统
充配电系统
整车与车身底盘
智能驾驶
智能座舱与车联网
制造工艺与装备
材料与化学
其他
```

The tag is selected by the core protected object of claim 1.

## Pipeline

1. Normalize the publication number.
2. Fetch `https://patents.google.com/patent/<publication_no>/zh`.
3. Extract current-patent metadata.
4. Extract all claim blocks from the Chinese claims section.
5. Detect formula/image placeholders.
6. If no placeholders exist, call GPT-5.5 with HTML claims only.
7. If placeholders exist, download the Google PDF, render claim pages, and call GPT-5.5 with the HTML claims plus claim-page images.
8. Validate the structured output.
9. Normalize all feature ids to `C{claim_no}-F{idx}`.
10. Derive claim 1 convenience fields from `claims`.
11. Write `task_package.json` when `output_dir` is supplied.

## Google Patents Extraction Rules

Claims are extracted from:

```html
<section itemprop="claims">
```

The parser prefers:

```html
<div class="claims" lang="ZH">
```

and falls back to the first claims block. This avoids mixing translated English claims when both languages are present.

Claim ids are accepted in both forms:

```text
cl0001
zh-cl0001
```

Duplicate claim nodes are removed by `(claim_no, first 30 chars of claim_text)`.

## Applicant Names

Google Patents often exposes current-patent assignees as English names, while backward reference tables contain unrelated Chinese assignees. The parser does not read assignees from backward references.

For known BYD entities, module one maps English assignee names to Chinese aliases because module two searches Chinese-market evidence:

```text
BYD Co Ltd -> 比亚迪股份有限公司
BYD Auto Co Ltd -> 比亚迪汽车工业有限公司
BYD Semiconductor Co Ltd -> 比亚迪半导体股份有限公司
```

Unknown assignees are left as Google Patents provides them. This avoids guessing company translations from unrelated reference tables.

## PDF Vision Path

When Google Patents HTML contains `patent-image-not-available`, module one downloads the official PDF and renders pages containing `权利要求书`.

Prompt rule:

```text
HTML 中无图片/公式/乱码占位的条目必须沿用 HTML 原文，不得用图片重新转写；只对存在异常的条目用图片还原。
```

Validation rule:

```text
HTML path: LLM claim numbers must exactly match HTML claim numbers.
PDF vision path: LLM claim count must be at least the HTML claim count, and the HTML claim-number prefix must match.
```

The relaxed PDF vision rule is intentional: if HTML has missing content but the PDF restores it, the module should not reject a more complete result solely because it has more claim entries.

## Commands

Run one patent:

```bash
uv run patentradar decompose CN105335144B --output-dir tests/decompose/outputs
```

Run configured end-to-end tests:

```bash
uv run python -m unittest tests.decompose.test_decompose.DecomposeTest.test_decompose_end_to_end_publications 2>&1 | tee tests/decompose/results/config_driven_e2e.log
```

Run full-pool non-LLM claims fetch:

```bash
uv run python tests/decompose/run_claims_fetch_pool.py 2>&1 | tee tests/decompose/results/claims_fetch_pool_run.log
```

Validate full-pool outputs:

```bash
uv run python -m unittest tests.decompose.test_claims_fetch_pool
```

## Test Inputs And Outputs

Configured end-to-end publications:

```text
tests/decompose/inputs/publications.json
```

Full patent pool extracted from the Excel attachment:

```text
tests/decompose/inputs/full_patent_pool.json
```

End-to-end outputs:

```text
tests/decompose/outputs/CN105335144B/task_package.json
tests/decompose/outputs/CN114512759B/task_package.json
tests/decompose/outputs/CN107423660B/task_package.json
```

Full-pool non-LLM claim outputs:

```text
tests/decompose/outputs/claims_fetch_pool/<publication_no>.json
```

Result summaries:

```text
tests/decompose/results/claims_fetch_pool_summary.json
tests/decompose/results/claims_fetch_pool_results.csv
tests/decompose/results/three_patents_e2e_summary.md
```

## Current Test Results

Full-pool non-LLM claim extraction:

```text
publication_count: 258
success_count: 258
failure_count: 0
```

Configured GPT-5.5 end-to-end tests:

```text
CN105335144B
CN114512759B
CN107423660B
```

Latest live GPT-5.5 rerun after the review fixes was attempted, but ChatGPT auth returned quota/rate-limit errors for all three patents. The result files were then deterministically normalized for non-LLM fields that changed in this pass: applicant aliases, feature id format, `claim_1_text`, `claim_1_features`, `model`, and `reasoning_effort`.

## Not Implemented Yet

The following suggestions were intentionally not implemented in this pass:

- LLM response caching. The current test workflow expects reruns to overwrite outputs and exercise live GPT-5.5 behavior. A cache should be added later with an explicit bypass flag.
- LLM self-repair retries for schema validation failures. No current failing sample requires it, and a repair loop would add extra GPT calls and make tests less deterministic.
- PDF page-boundary refactor. Current page detection worked on the tested PDF vision sample. A range-based extractor should be added only after collecting failing PDFs.
- Guessing claims when placeholders exist but `pdf_url` is unavailable. That would undermine the requirement to obtain complete accurate claims. The current behavior is to fail clearly rather than hallucinate missing formulas.
